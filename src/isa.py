"""ISA: определение системы команд процессора.

Архитектура: RISC, фон-Неймана (общая память команд и данных).
Машинное слово: 32 бита (знаковое).
Кодирование: фиксированная длина 32 бита (бинарный формат).

Регистры:
    - 8 целочисленных R0..R7 (R0 всегда = 0)
    - 4 векторных V0..V3, каждый из 4 элементов по 32 бита
    - PC, IR, FLAGS (Z, N), IE (interrupt enable), IN_HANDLER

Форматы инструкций (32 бита):

    R-тип (регистровая арифметика, 3 регистра):
        [ opcode:8 | rd:4 | rs1:4 | rs2:4 | unused:12 ]
        пример: ADD R1, R2, R3

    I-тип (регистр + непосредственный operand):
        [ opcode:8 | rd:4 | rs1:4 | imm:16 (знаковый) ]
        пример: ADDI R1, R2, 100; LW R1, R2(8); BEQ R1, R2, label

    J-тип (длинный переход):
        [ opcode:8 | rd:4 | imm:20 (знаковый) ]
        пример: JMP label; JAL R1, label

    V-тип (векторные инструкции):
        [ opcode:8 | vd:4 | vs1:4 | vs2:4 | unused:12 ]
        Векторные load/store: [ opcode:8 | vd:4 | rs1:4 | imm:16 ]

    S-тип (системные, без операндов):
        [ opcode:8 | unused:24 ]

ВНИМАНИЕ: На уровне ISA все целочисленные значения хранятся как 32-битные
дополнительные коды; функции encode/decode заботятся о знаке.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

# ----------- размеры в битах -----------------------------------------------
WORD_BITS = 32
WORD_MASK = (1 << WORD_BITS) - 1
WORD_MIN = -(1 << (WORD_BITS - 1))
WORD_MAX = (1 << (WORD_BITS - 1)) - 1

OPCODE_BITS = 8
REG_BITS = 4  # 16 регистров адресуемо (используем 8 скалярных + 4 векторных)
IMM16_BITS = 16
IMM20_BITS = 20


# ----------- параметры памяти / процессора ---------------------------------
MEMORY_SIZE = 2048  # размер ОЗУ в словах
VECTOR_LEN = 4  # длина векторного регистра в элементах
NUM_GP_REGS = 8  # R0..R7
NUM_VEC_REGS = 4  # V0..V3

# Memory-mapped I/O — последние ячейки памяти отдаются под порты.
# Согласно варианту `mem` это конфигурируется (здесь — hardcode).
IO_INPUT_ADDR = MEMORY_SIZE - 2  # 2046  — чтение даёт код символа из входа
IO_OUTPUT_ADDR = MEMORY_SIZE - 1  # 2047  — запись отправляет символ в вывод

# Адрес 0 — вектор прерывания (там лежит адрес обработчика).
# При сборке транслятор записывает туда `JMP handler`, либо
# программа сама делает `.org 0 / .word <addr>` — выберем второй путь:
# слово по адресу 0 трактуется как НЕПОСРЕДСТВЕННЫЙ адрес обработчика.
INTERRUPT_VECTOR_ADDR = 0
PROGRAM_START_DEFAULT = 1  # точка входа по умолчанию


class InstrType(IntEnum):
    """Тип (формат) инструкции — кодируется в старших 3 битах опкода.

    Это ключевое решение для hardwired control unit: чтобы определить
    формат инструкции, достаточно прочитать 3 старших бита опкода
    (`opcode >> 5`), а не искать опкод в таблице. В реальном железе это
    соответствует трём проводам, идущим прямо на дешифратор формата.
    """

    R = 0b000  # регистр-регистр-регистр:      [op|rd|rs1|rs2|--]
    I = 0b001  # noqa: E741  регистр-регистр-immediate16:  [op|rd|rs1|imm16]
    J = 0b010  # переходы:                     [op|rd|imm20]
    V = 0b011  # векторные регистр-регистр:    [op|vd|vs1|vs2|--]
    M = 0b100  # векторные load/store/bcast:   [op|vd|rs1|imm16]
    S = 0b101  # системные без операндов:      [op|--]


def _op(instr_type: InstrType, index: int) -> int:
    """Собрать байт опкода: старшие 3 бита — тип, младшие 5 — номер операции.

    Пример: _op(InstrType.I, 3) = 0b001_00011 = 0x23.
    """
    assert 0 <= index < 32, "не более 32 операций на тип"
    return (int(instr_type) << 5) | index


class Opcode(IntEnum):
    """Опкоды инструкций.

    Числовое значение опкода НЕ произвольно: старшие 3 бита задают тип
    инструкции (см. InstrType), младшие 5 бит — порядковый номер операции
    внутри типа. Благодаря этому декодер определяет формат инструкции
    одной битовой операцией `opcode >> 5`, без поиска по таблицам —
    это и есть «hardwired»-дешифрация.
    """

    # --- R-тип (0b000_xxxxx): арифметика регистр-регистр ---
    ADD = _op(InstrType.R, 0)  # 0x00
    SUB = _op(InstrType.R, 1)  # 0x01
    MUL = _op(InstrType.R, 2)  # 0x02
    DIV = _op(InstrType.R, 3)  # 0x03
    MOD = _op(InstrType.R, 4)  # 0x04
    AND = _op(InstrType.R, 5)  # 0x05
    OR = _op(InstrType.R, 6)  # 0x06
    XOR = _op(InstrType.R, 7)  # 0x07

    # --- I-тип (0b001_xxxxx): арифметика и память с immediate ---
    ADDI = _op(InstrType.I, 0)  # 0x20
    SUBI = _op(InstrType.I, 1)  # 0x21
    MULI = _op(InstrType.I, 2)  # 0x22
    ANDI = _op(InstrType.I, 3)  # 0x23
    ORI = _op(InstrType.I, 4)  # 0x24
    LW = _op(InstrType.I, 5)  # 0x25   load word:  Rd <- MEM[Rs1 + imm]
    SW = _op(InstrType.I, 6)  # 0x26   store word: MEM[Rs1 + imm] <- Rd
    LI = _op(InstrType.I, 7)  # 0x27   load immediate (знаковое 16-битное)
    LUI = _op(InstrType.I, 8)  # 0x28   load upper immediate: Rd <- imm << 16
    BEQ = _op(InstrType.I, 9)  # 0x29   if Rd == Rs1 then PC += imm
    BNE = _op(InstrType.I, 10)  # 0x2A
    BLT = _op(InstrType.I, 11)  # 0x2B   знаковое <
    BGT = _op(InstrType.I, 12)  # 0x2C
    BLE = _op(InstrType.I, 13)  # 0x2D
    BGE = _op(InstrType.I, 14)  # 0x2E

    # --- J-тип (0b010_xxxxx): переходы ---
    JMP = _op(InstrType.J, 0)  # 0x40
    JAL = _op(InstrType.J, 1)  # 0x41   jump-and-link: Rd <- PC; PC <- imm
    JR = _op(InstrType.J, 2)  # 0x42   jump register: PC <- Rd

    # --- V-тип (0b011_xxxxx): векторные регистр-регистр ---
    VADD = _op(InstrType.V, 0)  # 0x60   V[vd][i] <- V[vs1][i] + V[vs2][i]
    VSUB = _op(InstrType.V, 1)  # 0x61
    VMUL = _op(InstrType.V, 2)  # 0x62
    VDIV = _op(InstrType.V, 3)  # 0x63
    VCMP = _op(InstrType.V, 4)  # 0x64   V[vd][i] <- (V[vs1][i] == V[vs2][i])
    VRED = _op(InstrType.V, 5)  # 0x65   Rd <- сумма всех элементов V[vs1]

    # --- M-тип (0b100_xxxxx): векторные load/store и broadcast ---
    VLD = _op(InstrType.M, 0)  # 0x80   V[vd] <- MEM[Rs1 + imm .. +VLEN-1]
    VST = _op(InstrType.M, 1)  # 0x81   MEM[Rs1 + imm ..] <- V[vd]
    VBC = _op(InstrType.M, 2)  # 0x82   broadcast: V[vd][i] <- R[rs1]

    # --- S-тип (0b101_xxxxx): системные без операндов ---
    EI = _op(InstrType.S, 0)  # 0xA0   enable interrupts
    DI = _op(InstrType.S, 1)  # 0xA1   disable interrupts
    IRET = _op(InstrType.S, 2)  # 0xA2   возврат из обработчика прерывания
    HLT = _op(InstrType.S, 3)  # 0xA3   остановить процессор


def opcode_type(op: int) -> InstrType:
    """Извлечь тип инструкции из опкода — ОДНА битовая операция.

    Это и есть «hardwired»-дешифратор формата: в железе он сводится к
    тому, что три старших провода опкода идут на мультиплексор формата.
    """
    return InstrType((op >> 5) & 0b111)


# Опкоды, относящиеся к векторным инструкциям, — для удобства/документации.
# (Используются только для справки, в декодировании НЕ участвуют —
#  декодер опирается на биты типа.)
VECTOR_OPCODES = {
    Opcode.VLD,
    Opcode.VST,
    Opcode.VADD,
    Opcode.VSUB,
    Opcode.VMUL,
    Opcode.VDIV,
    Opcode.VCMP,
    Opcode.VRED,
    Opcode.VBC,
}

# Группировки опкодов по типу.  Они вычисляются ИЗ битов опкода
# (`opcode >> 5`), а не задаются вручную — то есть это просто удобные
# срезы, согласованные с дешифратором по построению. Транслятор
# использует их для проверки числа операндов.
R_TYPE_OPCODES = {op for op in Opcode if opcode_type(int(op)) == InstrType.R}
I_TYPE_OPCODES = {op for op in Opcode if opcode_type(int(op)) == InstrType.I}
J_TYPE_OPCODES = {op for op in Opcode if opcode_type(int(op)) == InstrType.J}
S_TYPE_OPCODES = {op for op in Opcode if opcode_type(int(op)) == InstrType.S}


# ----------- утилиты для знаковых / беззнаковых преобразований -------------
def to_unsigned(value: int, bits: int) -> int:
    """Преобразовать знаковое целое в беззнаковое представление в `bits` битах."""
    mask = (1 << bits) - 1
    return value & mask


def to_signed(value: int, bits: int) -> int:
    """Интерпретировать `bits`-битное беззнаковое значение как знаковое."""
    sign_bit = 1 << (bits - 1)
    mask = (1 << bits) - 1
    value &= mask
    if value & sign_bit:
        value -= 1 << bits
    return value


def clip_word(value: int) -> int:
    """Привести значение к диапазону 32-битного знакового слова (с переполнением)."""
    value &= WORD_MASK
    return to_signed(value, WORD_BITS)


# ----------- структура декодированной инструкции ---------------------------
@dataclass(frozen=True)
class Instruction:
    """Декодированный вид одной инструкции (удобно для интерпретатора)."""

    opcode: Opcode
    rd: int = 0  # регистр-приёмник (или vd для векторных)
    rs1: int = 0  # регистр-источник 1 (или vs1)
    rs2: int = 0  # регистр-источник 2 (или vs2)
    imm: int = 0  # непосредственный операнд (уже как знаковый int)
    raw: int = 0  # исходное 32-битное слово (для отладки)


# ----------- кодирование --------------------------------------------------
def encode(op: Opcode, *, rd: int = 0, rs1: int = 0, rs2: int = 0, imm: int = 0) -> int:
    """Закодировать инструкцию в 32-битное слово.

    Возвращает беззнаковое значение, которое нужно сохранить в память.
    Формат выбирается по ТИПУ инструкции (старшие биты опкода), а не по
    перечислению конкретных опкодов.
    """
    assert 0 <= rd < (1 << REG_BITS), f"rd  out of range: {rd}"
    assert 0 <= rs1 < (1 << REG_BITS), f"rs1 out of range: {rs1}"
    assert 0 <= rs2 < (1 << REG_BITS), f"rs2 out of range: {rs2}"

    t = opcode_type(int(op))
    base = int(op) << 24

    if t in (InstrType.R, InstrType.V):
        # три регистровых поля; VRED — частный случай (vs2 не используется)
        word = base | (rd << 20) | (rs1 << 16) | (rs2 << 12)
    elif t in (InstrType.I, InstrType.M):
        imm_u = to_unsigned(imm, IMM16_BITS)
        word = base | (rd << 20) | (rs1 << 16) | imm_u
    elif t == InstrType.J:
        imm_u = to_unsigned(imm, IMM20_BITS)
        word = base | (rd << 20) | imm_u
    elif t == InstrType.S:
        word = base
    else:
        raise ValueError(f"encode: неизвестный тип для opcode {op}")
    return word & WORD_MASK


def decode(word: int) -> Instruction:
    """Декодировать 32-битное слово в Instruction.

    Формат определяется ТИПОМ инструкции (`opcode >> 5`) — это и есть
    hardwired-дешифрация: одна битовая операция вместо поиска по таблице.
    """
    word &= WORD_MASK
    op_val = (word >> 24) & 0xFF
    try:
        op = Opcode(op_val)
    except ValueError as e:
        raise ValueError(f"decode: неизвестный opcode 0x{op_val:02X}") from e

    rd = (word >> 20) & 0xF
    rs1 = (word >> 16) & 0xF
    rs2 = (word >> 12) & 0xF
    imm16 = to_signed(word & 0xFFFF, IMM16_BITS)
    imm20 = to_signed(word & 0xFFFFF, IMM20_BITS)

    t = opcode_type(op_val)
    if t in (InstrType.R, InstrType.V):
        return Instruction(op, rd=rd, rs1=rs1, rs2=rs2, raw=word)
    if t in (InstrType.I, InstrType.M):
        return Instruction(op, rd=rd, rs1=rs1, imm=imm16, raw=word)
    if t == InstrType.J:
        return Instruction(op, rd=rd, imm=imm20, raw=word)
    if t == InstrType.S:
        return Instruction(op, raw=word)
    raise ValueError(f"decode: opcode {op} не имеет описанного формата")


# ----------- удобные мнемонические строки для отладочного дампа -----------
def mnemonic(instr: Instruction) -> str:
    """Вернуть человекочитаемую запись инструкции."""
    op = instr.opcode
    t = opcode_type(int(op))

    if t == InstrType.R:
        return f"{op.name} R{instr.rd}, R{instr.rs1}, R{instr.rs2}"
    if t == InstrType.I:
        if op in {Opcode.LW, Opcode.SW}:
            return f"{op.name} R{instr.rd}, {instr.imm}(R{instr.rs1})"
        if op in {Opcode.LI, Opcode.LUI}:
            return f"{op.name} R{instr.rd}, {instr.imm}"
        if op in {Opcode.BEQ, Opcode.BNE, Opcode.BLT, Opcode.BGT, Opcode.BLE, Opcode.BGE}:
            return f"{op.name} R{instr.rd}, R{instr.rs1}, {instr.imm:+d}"
        return f"{op.name} R{instr.rd}, R{instr.rs1}, {instr.imm}"
    if t == InstrType.J:
        if op == Opcode.JMP:
            return f"JMP {instr.imm}"
        if op == Opcode.JAL:
            return f"JAL R{instr.rd}, {instr.imm}"
        return f"JR R{instr.rd}"
    if t == InstrType.V:
        if op == Opcode.VRED:
            return f"VRED R{instr.rd}, V{instr.rs1}"
        return f"{op.name} V{instr.rd}, V{instr.rs1}, V{instr.rs2}"
    if t == InstrType.M:
        if op == Opcode.VBC:
            return f"VBC V{instr.rd}, R{instr.rs1}"
        return f"{op.name} V{instr.rd}, {instr.imm}(R{instr.rs1})"
    # остаётся только S-тип (системные инструкции без операндов)
    return op.name
