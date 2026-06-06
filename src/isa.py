from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

#  размеры в битах
WORD_BITS = 32
WORD_MASK = (1 << WORD_BITS) - 1
WORD_MIN = -(1 << (WORD_BITS - 1))
WORD_MAX = (1 << (WORD_BITS - 1)) - 1

OPCODE_BITS = 8
REG_BITS = 4  # 16 регистров
IMM16_BITS = 16
IMM20_BITS = 20


#  параметры памяти / процессора
WORD_BYTES = WORD_BITS // 8
MEMORY_SIZE = 8192  # размер ОЗУ в байтах; память байтово-адресуемая
VECTOR_LEN = 4  # длина векторного регистра в элементах
NUM_GP_REGS = 8  # R0..R7
NUM_VEC_REGS = 4  # V0..V3

# Memory-mapped I/O
IO_INPUT_ADDR = MEMORY_SIZE - 2 * WORD_BYTES  # 8184 — чтение символа из входа
IO_OUTPUT_ADDR = MEMORY_SIZE - WORD_BYTES  # 8188 — запись символа в вывод

# Адрес 0 — вектор прерывания (там лежит адрес обработчика).

INTERRUPT_VECTOR_ADDR = 0
PROGRAM_START_DEFAULT = WORD_BYTES  # адрес 4


class InstrType(IntEnum):
    """Тип (формат) инструкции — кодируется в старших 3 битах опкода."""

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
    """Опкоды инструкций."""

    #  R-тип
    ADD = _op(InstrType.R, 0)  # 0x00
    SUB = _op(InstrType.R, 1)  # 0x01
    MUL = _op(InstrType.R, 2)  # 0x02
    DIV = _op(InstrType.R, 3)  # 0x03
    MOD = _op(InstrType.R, 4)  # 0x04
    AND = _op(InstrType.R, 5)  # 0x05
    OR = _op(InstrType.R, 6)  # 0x06
    XOR = _op(InstrType.R, 7)  # 0x07

    #  I-тип
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

    #  J-тип
    JMP = _op(InstrType.J, 0)  # 0x40
    JAL = _op(InstrType.J, 1)  # 0x41   jump-and-link: Rd <- PC; PC <- imm
    JR = _op(InstrType.J, 2)  # 0x42   jump register: PC <- Rd

    #  V-тип
    VADD = _op(InstrType.V, 0)  # 0x60   V[vd][i] <- V[vs1][i] + V[vs2][i]
    VSUB = _op(InstrType.V, 1)  # 0x61
    VMUL = _op(InstrType.V, 2)  # 0x62
    VDIV = _op(InstrType.V, 3)  # 0x63
    VCMP = _op(InstrType.V, 4)  # 0x64   V[vd][i] <- (V[vs1][i] == V[vs2][i])
    VRED = _op(InstrType.V, 5)  # 0x65   Rd <- сумма  элементов V[vs1]

    #  M-тип
    VLD = _op(InstrType.M, 0)  # 0x80   V[vd] <- MEM[Rs1 + imm .. +VLEN-1]
    VST = _op(InstrType.M, 1)  # 0x81   MEM[Rs1 + imm ..] <- V[vd]
    VBC = _op(InstrType.M, 2)  # 0x82   broadcast: V[vd][i] <- R[rs1]

    #  S-тип
    EI = _op(InstrType.S, 0)  # 0xA0   enable interrupts
    DI = _op(InstrType.S, 1)  # 0xA1   disable interrupts
    IRET = _op(InstrType.S, 2)  # 0xA2   возврат из обработчика прерывания
    HLT = _op(InstrType.S, 3)  # 0xA3   остановить процессор


def opcode_type(op: int) -> InstrType:
    return InstrType((op >> 5) & 0b111)


# Опкоды, относящиеся к векторным инструкциям
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

# Группировки опкодов по типу.

R_TYPE_OPCODES = {op for op in Opcode if opcode_type(int(op)) == InstrType.R}
I_TYPE_OPCODES = {op for op in Opcode if opcode_type(int(op)) == InstrType.I}
J_TYPE_OPCODES = {op for op in Opcode if opcode_type(int(op)) == InstrType.J}
S_TYPE_OPCODES = {op for op in Opcode if opcode_type(int(op)) == InstrType.S}


# утилиты для знаковых / беззнаковых преобразований
def to_unsigned(value: int, bits: int) -> int:
    mask = (1 << bits) - 1
    return value & mask


def to_signed(value: int, bits: int) -> int:
    sign_bit = 1 << (bits - 1)
    mask = (1 << bits) - 1
    value &= mask
    if value & sign_bit:
        value -= 1 << bits
    return value


def clip_word(value: int) -> int:
    value &= WORD_MASK
    return to_signed(value, WORD_BITS)


#  структура декодированной инструкции
@dataclass(frozen=True)
class Instruction:
    opcode: Opcode
    rd: int = 0  # регистр-приёмник (или vd для векторных)
    rs1: int = 0  # регистр-источник 1 (или vs1)
    rs2: int = 0  # регистр-источник 2 (или vs2)
    imm: int = 0  # непосредственный операнд (уже как знаковый int)
    raw: int = 0  # исходное 32-битное слово (для отладки)


#  кодирование
def encode(op: Opcode, *, rd: int = 0, rs1: int = 0, rs2: int = 0, imm: int = 0) -> int:
    """Закодировать инструкцию в 32-битное слово."""
    assert 0 <= rd < (1 << REG_BITS), f"rd  out of range: {rd}"
    assert 0 <= rs1 < (1 << REG_BITS), f"rs1 out of range: {rs1}"
    assert 0 <= rs2 < (1 << REG_BITS), f"rs2 out of range: {rs2}"

    t = opcode_type(int(op))
    base = int(op) << 24

    if t in (InstrType.R, InstrType.V):
        # три регистровых поля;
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
    """Декодировать 32-битное слово в Instruction."""
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


#  удобные мнемонические строки для отладочного дампа
def mnemonic(instr: Instruction) -> str:
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
