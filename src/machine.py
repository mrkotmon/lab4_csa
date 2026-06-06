

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import IO, ClassVar

from isa import (
    INTERRUPT_VECTOR_ADDR,
    IO_INPUT_ADDR,
    IO_OUTPUT_ADDR,
    MEMORY_SIZE,
    NUM_GP_REGS,
    NUM_VEC_REGS,
    VECTOR_LEN,
    WORD_BYTES,
    WORD_MASK,
    Instruction,
    Opcode,
    clip_word,
    decode,
    mnemonic,
    to_signed,
    to_unsigned,
)


class Stage(Enum):
    FETCH = auto()
    DECODE = auto()
    EXECUTE = auto()
    MEMORY = auto()
    WRITEBACK = auto()
    CHECK_IRQ = auto()
    HALTED = auto()


@dataclass
class InputSchedule:
    """Расписание ввода: список """

    schedule: list[tuple[int, str]]
    _idx: int = 0

    def has_pending(self, current_tick: int) -> bool:
        return self._idx < len(self.schedule) and self.schedule[self._idx][0] <= current_tick

    def peek(self) -> tuple[int, str] | None:
        if self._idx < len(self.schedule):
            return self.schedule[self._idx]
        return None

    def pop(self) -> tuple[int, str]:
        item = self.schedule[self._idx]
        self._idx += 1
        return item


# DataPath
@dataclass
class DataPath:
    """Тракт данных с единой байтово-адресуемой памятью фон Неймана."""

    memory: bytearray = field(default_factory=lambda: bytearray(MEMORY_SIZE))

    # Скалярные регистры
    regs: list[int] = field(default_factory=lambda: [0] * NUM_GP_REGS)
    # Векторные регистры: список из NUM_VEC_REGS списков длины VECTOR_LEN.
    vregs: list[list[int]] = field(
        default_factory=lambda: [[0] * VECTOR_LEN for _ in range(NUM_VEC_REGS)]
    )
    pc: int = 0
    ir: int = 0
    saved_pc: int = 0
    saved_flags: int = 0
    flags: int = 0  # bit0 = Z, bit1 = N
    ie: bool = False
    in_handler: bool = False

    _input_port: int = 0
    _on_output: Callable[[int], None] = field(default=lambda _code: None, repr=False)

    def read_reg(self, idx: int) -> int:
        if idx == 0:
            return 0
        return self.regs[idx]

    def write_reg(self, idx: int, value: int) -> None:
        if idx != 0:
            self.regs[idx] = clip_word(value)

    @staticmethod
    def _require_word_address(addr: int) -> None:
        if addr % WORD_BYTES != 0:
            raise RuntimeError(f"невыровненный адрес 32-битного слова: {addr}")
        if not 0 <= addr <= MEMORY_SIZE - WORD_BYTES:
            raise RuntimeError(f"адрес {addr} вне памяти")

    def load_word(self, addr: int, value: int) -> None:
        """Загрузить слово образа в ОЗУ, минуя побочный эффект I/O."""
        self._require_word_address(addr)
        unsigned = to_unsigned(clip_word(value), 32)
        self.memory[addr : addr + WORD_BYTES] = unsigned.to_bytes(WORD_BYTES, "little")

    def read_mem(self, addr: int) -> int:
        self._require_word_address(addr)
        if addr == IO_INPUT_ADDR:
            return self._input_port
        return int.from_bytes(self.memory[addr : addr + WORD_BYTES], "little")

    def write_mem(self, addr: int, value: int) -> None:
        self._require_word_address(addr)
        if addr == IO_OUTPUT_ADDR:
            self._on_output(value & 0xFFFF)
            return
        self.load_word(addr, value)


# Сам процессор
class Processor:
    """Симулирует процессор с точностью до такта."""

    # Имена векторных операций для журнала
    _VEC_OP_NAMES: ClassVar[dict[Opcode, str]] = {
        Opcode.VADD: "+",
        Opcode.VSUB: "-",
        Opcode.VMUL: "*",
        Opcode.VDIV: "/",
        Opcode.VCMP: "==",
    }

    def __init__(
        self,
        memory_image: dict[int, int],
        entry_point: int,
        input_schedule: InputSchedule | None = None,
        *,
        log_stream: IO[str] | None = None,
        max_ticks: int = 100_000,
    ) -> None:
        self.dp = DataPath()
        for addr, word in memory_image.items():
            self.dp.load_word(addr, word & WORD_MASK)
        self.dp.pc = entry_point
        # сценарий ввода
        self.input_schedule = input_schedule or InputSchedule([])
        # буфер вывода (коды символов)
        self.output_buffer: list[int] = []
        # подключаем I/O к DataPath
        self.dp._on_output = self.output_buffer.append
        # ограничители
        self.tick: int = 0
        self.max_ticks = max_ticks
        # счётчики инструкций
        self.instruction_count = 0
        # состояние FSM
        self.stage: Stage = Stage.FETCH
        self.cur: Instruction | None = None
        # Входное устройство
        self._irq_pending: bool = False
        self._input_active_char: str | None = None
        self.input_overrun_count: int = 0
        # журнал
        self.log_stream = log_stream
        # счётчик активных стадий для VLD/VST (имитация многотактовой Sпамяти)
        self._mem_remaining_words: int = 0

    #  журналирование
    def _log(self, msg: str) -> None:
        if self.log_stream is not None:
            mark = "*" if self.dp.in_handler else " "
            self.log_stream.write(
                f"[tick={self.tick:5d}] [PC={self.dp.pc:4d}] "
                f"[stage={self.stage.name:<9}] {mark} {msg}\n"
            )

    def _reg_dump(self) -> str:
        rs = " ".join(f"R{i}={self.dp.regs[i]}" for i in range(NUM_GP_REGS))
        return rs + f"  FLAGS={self.dp.flags} IE={int(self.dp.ie)} IH={int(self.dp.in_handler)}"

    #  обновление flags после ALU
    def _set_flags(self, value: int) -> None:
        z = 1 if value == 0 else 0
        n = 1 if value < 0 else 0
        self.dp.flags = z | (n << 1)

    #  запрос прерывания
    def _check_input_event(self) -> None:
        """Принять все события текущего такта в однословный аппаратный порт
        """
        while self.input_schedule.has_pending(self.tick):
            _, ch = self.input_schedule.pop()
            if self._input_active_char is not None:
                self.input_overrun_count += 1
                self._log(f"INPUT OVERRUN: символ '{_print_char(ch)}' потерян; регистр ввода занят")
                continue
            self._input_active_char = ch
            self.dp._input_port = ord(ch)
            self._irq_pending = True
            self._log(f"IRQ: появился символ '{_print_char(ch)}' (код {ord(ch)})")

    #  основной цикл
    def run(self) -> None:
        """Прокручиваем такты, пока не HLT или не закончится лимит."""
        while self.stage != Stage.HALTED and self.tick < self.max_ticks:
            self._tick_once()
        if self.stage != Stage.HALTED:
            self._log("STOP: достигнут лимит тактов")
            raise RuntimeError("достигнут лимит тактов до выполнения HLT")

    def _tick_once(self) -> None:
        """Один такт."""
        # Перед стадией: новые внешние события.
        self._check_input_event()

        if self.stage == Stage.FETCH:
            self._stage_fetch()
        elif self.stage == Stage.DECODE:
            self._stage_decode()
        elif self.stage == Stage.EXECUTE:
            self._stage_execute()
        elif self.stage == Stage.MEMORY:
            self._stage_memory()
        elif self.stage == Stage.WRITEBACK:
            self._stage_writeback()
        elif self.stage == Stage.CHECK_IRQ:
            self._stage_check_irq()
        else:
            # HALTED
            pass

        self.tick += 1

    #  отдельные стадии
    def _stage_fetch(self) -> None:
        word = self.dp.read_mem(self.dp.pc)
        self.dp.ir = word
        self.cur = decode(word)
        self._log(f"FETCH word=0x{word:08X} ({mnemonic(self.cur)})")
        self.dp.pc += WORD_BYTES
        self.stage = Stage.DECODE

    def _stage_decode(self) -> None:
        # «Аппаратный» дешифратор уже отработал в _stage_fetch
        assert self.cur is not None
        self._log(f"DECODE {mnemonic(self.cur)}")
        self.stage = Stage.EXECUTE

    def _stage_execute(self) -> None:
        assert self.cur is not None
        instr = self.cur
        op = instr.opcode
        dp = self.dp

        # Большинство ALU операций укладываются в один такт.
        if op == Opcode.ADD:
            res = dp.read_reg(instr.rs1) + dp.read_reg(instr.rs2)
            self._alu_result = clip_word(res)
            self._has_writeback = True
        elif op == Opcode.SUB:
            res = dp.read_reg(instr.rs1) - dp.read_reg(instr.rs2)
            self._alu_result = clip_word(res)
            self._has_writeback = True
        elif op == Opcode.MUL:
            res = dp.read_reg(instr.rs1) * dp.read_reg(instr.rs2)
            self._alu_result = clip_word(res)
            self._has_writeback = True
        elif op == Opcode.DIV:
            a, b = dp.read_reg(instr.rs1), dp.read_reg(instr.rs2)
            if b == 0:
                raise RuntimeError(f"DIV by zero на PC={dp.pc - WORD_BYTES}")
            # «обычное» целочисленное деление к нулю
            res = int(a / b) if (a < 0) ^ (b < 0) and a % b != 0 else a // b
            self._alu_result = clip_word(res)
            self._has_writeback = True
        elif op == Opcode.MOD:
            a, b = dp.read_reg(instr.rs1), dp.read_reg(instr.rs2)
            if b == 0:
                raise RuntimeError(f"MOD by zero на PC={dp.pc - WORD_BYTES}")
            self._alu_result = clip_word(
                a - (int(a / b) if (a < 0) ^ (b < 0) and a % b != 0 else a // b) * b
            )
            self._has_writeback = True
        elif op == Opcode.AND:
            self._alu_result = clip_word(dp.read_reg(instr.rs1) & dp.read_reg(instr.rs2))
            self._has_writeback = True
        elif op == Opcode.OR:
            self._alu_result = clip_word(dp.read_reg(instr.rs1) | dp.read_reg(instr.rs2))
            self._has_writeback = True
        elif op == Opcode.XOR:
            self._alu_result = clip_word(dp.read_reg(instr.rs1) ^ dp.read_reg(instr.rs2))
            self._has_writeback = True
        elif op == Opcode.ADDI:
            self._alu_result = clip_word(dp.read_reg(instr.rs1) + instr.imm)
            self._has_writeback = True
        elif op == Opcode.SUBI:
            self._alu_result = clip_word(dp.read_reg(instr.rs1) - instr.imm)
            self._has_writeback = True
        elif op == Opcode.MULI:
            self._alu_result = clip_word(dp.read_reg(instr.rs1) * instr.imm)
            self._has_writeback = True
        elif op == Opcode.ANDI:
            # immediate трактуется как 16-битная беззнаковая маска
            self._alu_result = clip_word(dp.read_reg(instr.rs1) & (instr.imm & 0xFFFF))
            self._has_writeback = True
        elif op == Opcode.ORI:
            self._alu_result = clip_word(dp.read_reg(instr.rs1) | (instr.imm & 0xFFFF))
            self._has_writeback = True
        elif op == Opcode.LI:
            self._alu_result = instr.imm
            self._has_writeback = True
        elif op == Opcode.LUI:
            # старшие 16 бит результата = беззнаковый immediate
            self._alu_result = clip_word((instr.imm & 0xFFFF) << 16)
            self._has_writeback = True
        elif op == Opcode.LW:
            # вычислили эффективный адрес — само чтение в стадии MEMORY
            self._effective_addr = dp.read_reg(instr.rs1) + instr.imm
            self._has_writeback = True
        elif op == Opcode.SW:
            self._effective_addr = dp.read_reg(instr.rs1) + instr.imm
            self._store_value = dp.read_reg(instr.rd)
            self._has_writeback = False
        elif op in (Opcode.BEQ, Opcode.BNE, Opcode.BLT, Opcode.BGT, Opcode.BLE, Opcode.BGE):
            a = dp.read_reg(instr.rd)
            b = dp.read_reg(instr.rs1)
            cond = {
                Opcode.BEQ: a == b,
                Opcode.BNE: a != b,
                Opcode.BLT: a < b,
                Opcode.BGT: a > b,
                Opcode.BLE: a <= b,
                Opcode.BGE: a >= b,
            }[op]
            self._log(f"  branch test: R{instr.rd}={a} vs R{instr.rs1}={b} -> {cond}")
            if cond:
                dp.pc = clip_word(dp.pc + instr.imm)
            self._has_writeback = False
        elif op == Opcode.JMP:
            dp.pc = instr.imm
            self._has_writeback = False
        elif op == Opcode.JAL:
            self._alu_result = dp.pc  # PC указывает на следующую инструкцию
            self._has_writeback = True
            dp.pc = instr.imm
        elif op == Opcode.JR:
            dp.pc = dp.read_reg(instr.rd)
            self._has_writeback = False
        elif op in (Opcode.VADD, Opcode.VSUB, Opcode.VMUL, Opcode.VDIV, Opcode.VCMP):
            v1 = dp.vregs[instr.rs1]
            v2 = dp.vregs[instr.rs2]
            result: list[int] = []
            for i in range(VECTOR_LEN):
                a, b = v1[i], v2[i]
                if op == Opcode.VADD:
                    r = a + b
                elif op == Opcode.VSUB:
                    r = a - b
                elif op == Opcode.VMUL:
                    r = a * b
                elif op == Opcode.VDIV:
                    if b == 0:
                        raise RuntimeError("VDIV by zero")
                    r = int(a / b) if (a < 0) ^ (b < 0) and a % b != 0 else a // b
                else:  # VCMP
                    r = 1 if a == b else 0
                result.append(clip_word(r))
            self._vec_result = result
            self._has_writeback = True
            self._log(
                f"  V{instr.rs1}={v1} {self._VEC_OP_NAMES[op]} V{instr.rs2}={v2} "
                f"-> V{instr.rd}={result}  (4 элемента за 1 такт ALU!)"
            )
        elif op == Opcode.VBC:
            val = dp.read_reg(instr.rs1)
            self._vec_result = [val] * VECTOR_LEN
            self._has_writeback = True
        elif op == Opcode.VRED:
            v = dp.vregs[instr.rs1]
            res = sum(v)
            self._alu_result = clip_word(res)
            self._has_writeback = True
            self._log(f"  VRED V{instr.rs1}={v} -> R{instr.rd}={res}")
        elif op == Opcode.VLD:
            self._effective_addr = dp.read_reg(instr.rs1) + instr.imm
            self._has_writeback = True
            self._mem_remaining_words = VECTOR_LEN
        elif op == Opcode.VST:
            self._effective_addr = dp.read_reg(instr.rs1) + instr.imm
            self._has_writeback = False
            self._mem_remaining_words = VECTOR_LEN
        elif op == Opcode.EI:
            dp.ie = True
            self._has_writeback = False
            self._log("  interrupts ENABLED")
        elif op == Opcode.DI:
            dp.ie = False
            self._has_writeback = False
            self._log("  interrupts DISABLED")
        elif op == Opcode.IRET:
            dp.pc = dp.saved_pc
            dp.flags = dp.saved_flags
            dp.in_handler = False
            self._has_writeback = False
            self._log(f"  IRET -> возврат на PC={dp.pc}")
        elif op == Opcode.HLT:
            self.stage = Stage.HALTED
            self._log("HALT")
            self.instruction_count += 1
            return
        else:
            raise RuntimeError(f"EXECUTE: неизвестный opcode {op}")

        self._log(f"EXECUTE {mnemonic(instr)}")
        # выбираем следующую стадию
        if op in (Opcode.LW, Opcode.SW, Opcode.VLD, Opcode.VST):
            self.stage = Stage.MEMORY
        elif getattr(self, "_has_writeback", False):
            self.stage = Stage.WRITEBACK
        else:
            self.stage = Stage.CHECK_IRQ

    def _stage_memory(self) -> None:
        assert self.cur is not None
        instr = self.cur
        op = instr.opcode
        dp = self.dp
        if op == Opcode.LW:
            value = dp.read_mem(self._effective_addr)
            self._alu_result = to_signed(value, 32)
            self._log(f"MEMORY LW addr={self._effective_addr} -> {self._alu_result}")
            if self._effective_addr == IO_INPUT_ADDR:
                self._consume_input()
            self.stage = Stage.WRITEBACK
        elif op == Opcode.SW:
            dp.write_mem(self._effective_addr, self._store_value)
            self._log(f"MEMORY SW addr={self._effective_addr} val={self._store_value}")
            self.stage = Stage.CHECK_IRQ
        elif op == Opcode.VLD:
            # многотактовая память: читаем по одному слову за такт
            idx = VECTOR_LEN - self._mem_remaining_words
            value = dp.read_mem(self._effective_addr + idx * WORD_BYTES)
            dp.vregs[instr.rd][idx] = to_signed(value, 32)
            self._log(
                f"MEMORY VLD[{idx}] addr={self._effective_addr + idx * WORD_BYTES} -> "
                f"V{instr.rd}[{idx}]={dp.vregs[instr.rd][idx]}"
            )
            self._mem_remaining_words -= 1
            if self._mem_remaining_words == 0:
                self.stage = Stage.CHECK_IRQ  # writeback уже сделан поэлементно
        elif op == Opcode.VST:
            idx = VECTOR_LEN - self._mem_remaining_words
            value = dp.vregs[instr.rd][idx]
            dp.write_mem(self._effective_addr + idx * WORD_BYTES, value)
            self._log(
                f"MEMORY VST[{idx}] V{instr.rd}[{idx}]={value} -> "
                f"addr={self._effective_addr + idx * WORD_BYTES}"
            )
            self._mem_remaining_words -= 1
            if self._mem_remaining_words == 0:
                self.stage = Stage.CHECK_IRQ
        else:
            raise RuntimeError(f"MEMORY: некорректный op {op}")

    def _stage_writeback(self) -> None:
        assert self.cur is not None
        instr = self.cur
        op = instr.opcode
        dp = self.dp
        if op in (Opcode.VADD, Opcode.VSUB, Opcode.VMUL, Opcode.VDIV, Opcode.VCMP, Opcode.VBC):
            dp.vregs[instr.rd] = list(self._vec_result)
            self._log(f"WRITEBACK V{instr.rd} <- {dp.vregs[instr.rd]}")
        else:
            dp.write_reg(instr.rd, self._alu_result)
            # flags обновляем для арифметики (только для скалярных).
            if op in (
                Opcode.ADD,
                Opcode.SUB,
                Opcode.MUL,
                Opcode.DIV,
                Opcode.MOD,
                Opcode.AND,
                Opcode.OR,
                Opcode.XOR,
                Opcode.ADDI,
                Opcode.SUBI,
                Opcode.MULI,
                Opcode.ANDI,
                Opcode.ORI,
            ):
                self._set_flags(self._alu_result)
            self._log(f"WRITEBACK R{instr.rd} <- {self._alu_result}")
        self.stage = Stage.CHECK_IRQ

    def _stage_check_irq(self) -> None:
        """После завершения каждой инструкции проверяем запрос прерывания."""
        self.instruction_count += 1
        # Проверяем «созревание» события на этом такте.
        self._check_input_event()
        dp = self.dp
        if self._irq_pending and dp.ie and not dp.in_handler:
            handler_addr = to_signed(dp.read_mem(INTERRUPT_VECTOR_ADDR), 32)
            dp.saved_pc = dp.pc
            dp.saved_flags = dp.flags
            dp.in_handler = True
            self._log(
                f"CHECK_IRQ: запрос есть, IE=1, IH=0 -> переход в обработчик "
                f"по адресу {handler_addr} (saved_pc={dp.saved_pc})"
            )
            dp.pc = handler_addr
            # Запрос сбрасывается только чтением порта;
            self.stage = Stage.FETCH
            return
        if self._irq_pending:
            reason = []
            if not dp.ie:
                reason.append("IE=0")
            if dp.in_handler:
                reason.append("IH=1 (nested)")
            self._log(f"CHECK_IRQ: запрос есть, но {', '.join(reason)} — откладываем")
        self.stage = Stage.FETCH

    def _consume_input(self) -> None:
        """Вызывается, когда LW обращается к адресу IO_INPUT_ADDR.
        Сбрасывает запрос и активный символ."""
        if self._input_active_char is not None:
            self._log(
                f"  CONSUME: прочитан символ "
                f"'{_print_char(self._input_active_char)}' из порта ввода"
            )
            self._input_active_char = None
            self._irq_pending = False


def _print_char(ch: str) -> str:
    if ch == "\n":
        return "\\n"
    if ch == "\t":
        return "\\t"
    if ch == "\0":
        return "\\0"
    return ch


# CLI
def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    from translator import load_binary

    parser = argparse.ArgumentParser(description="Симулятор RISC-процессора")
    parser.add_argument("binary", help="бинарный файл с программой")
    parser.add_argument(
        "input",
        nargs="?",
        help="файл с расписанием ввода (JSON со списком "
        "[[tick, char], ...]); если не указан без ввода",
    )
    parser.add_argument("--log", help="куда писать журнал тактов", default=None)
    parser.add_argument("--max-ticks", type=int, default=200_000)
    args = parser.parse_args(argv)

    with open(args.binary, "rb") as f:
        entry, memory = load_binary(f.read())

    schedule: list[tuple[int, str]] = []
    if args.input:
        import json

        with open(args.input, encoding="utf-8") as f:
            schedule = [(int(t), str(c)) for t, c in json.load(f)]

    import contextlib

    with contextlib.ExitStack() as stack:
        log_stream: IO[str] | None = None
        if args.log:
            log_stream = stack.enter_context(open(args.log, "w", encoding="utf-8"))

        proc = Processor(
            memory,
            entry,
            input_schedule=InputSchedule(schedule),
            log_stream=log_stream,
            max_ticks=args.max_ticks,
        )
        try:
            proc.run()
        except RuntimeError as e:
            print(f"Ошибка симуляции: {e}", file=sys.stderr)
            return 1

    # Печатаем вывод
    output_text = "".join(chr(c) for c in proc.output_buffer)
    print("=" * 50)
    print("OUTPUT:")
    print(output_text, end="")
    if not output_text.endswith("\n"):
        print()
    print("=" * 50)
    print(f"Tаkтов исполнено:    {proc.tick}")
    print(f"Инструкций исполнено: {proc.instruction_count}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
