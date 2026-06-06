

from __future__ import annotations

import re
import struct
import sys
from dataclasses import dataclass, field

from isa import (
    I_TYPE_OPCODES,
    IMM16_BITS,
    IMM20_BITS,
    MEMORY_SIZE,
    PROGRAM_START_DEFAULT,
    R_TYPE_OPCODES,
    S_TYPE_OPCODES,
    WORD_BYTES,
    Opcode,
    clip_word,
    decode,
    encode,
    mnemonic,
    to_signed,
    to_unsigned,
)


# Лексер
@dataclass
class Line:
    """Одна логическая строка исходника после удаления комментариев."""

    text: str
    src_line_no: int


def _strip_comment(line: str) -> str:
    in_quotes = False
    out: list[str] = []
    for ch in line:
        if ch == '"':
            in_quotes = not in_quotes
        if ch == ";" and not in_quotes:
            break
        out.append(ch)
    return "".join(out)


def _read_lines(source: str) -> list[Line]:
    """Поделить исходник на строки"""
    result: list[Line] = []
    for i, raw in enumerate(source.splitlines(), start=1):
        clean = _strip_comment(raw).strip()
        if clean:
            result.append(Line(text=clean, src_line_no=i))
    return result


# Препроцессор: .equ + макросы
_RE_EQU = re.compile(r"^\.equ\s+(\w+)\s+(.+)$")
_RE_MACRO_START = re.compile(r"^\.macro\s+(\w+)(.*)$")
_RE_MACRO_END = re.compile(r"^\.endm\s*$")


@dataclass
class Macro:
    name: str
    params: list[str]
    body: list[Line]


def _condition_is_true(expr: str, constants: dict[str, str], src_line_no: int) -> bool:
    """Вычислить простое условие препроцессора после подстановки `.equ`.

    """
    replaced = _replace_tokens(expr.strip(), constants).strip()
    negate = replaced.startswith("!")
    if negate:
        replaced = replaced[1:].strip()
    try:
        result = _parse_int(replaced) != 0
    except ValueError as exc:
        raise SyntaxError(
            f"строка {src_line_no}: условие .if должно быть константой или числом, "
            f"получено {expr!r}"
        ) from exc
    return not result if negate else result


def _preprocess(lines: list[Line]) -> list[Line]:
    """Раскрыть `.equ`, `.if/.else/.endif` и пользовательские макросы.

    """
    constants: dict[str, str] = {}
    macros: dict[str, Macro] = {}
    out: list[Line] = []
    active: list[bool] = [True]
    branch_taken: list[bool] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        text = line.text
        lower = text.lower()

        if lower.startswith(".if "):
            parent_active = active[-1]
            take = parent_active and _condition_is_true(
                text.split(None, 1)[1], constants, line.src_line_no
            )
            active.append(take)
            branch_taken.append(take)
            i += 1
            continue
        if lower == ".else":
            if len(active) == 1:
                raise SyntaxError(f"строка {line.src_line_no}: .else без .if")
            parent_active = active[-2]
            active[-1] = parent_active and not branch_taken[-1]
            branch_taken[-1] = True
            i += 1
            continue
        if lower == ".endif":
            if len(active) == 1:
                raise SyntaxError(f"строка {line.src_line_no}: .endif без .if")
            active.pop()
            branch_taken.pop()
            i += 1
            continue
        if not active[-1]:
            i += 1
            continue

        m = _RE_EQU.match(text)
        if m:
            constants[m.group(1)] = _replace_tokens(m.group(2).strip(), constants)
            i += 1
            continue

        m = _RE_MACRO_START.match(text)
        if m:
            name = m.group(1)
            params = m.group(2).split()
            body: list[Line] = []
            i += 1
            while i < len(lines) and not _RE_MACRO_END.match(lines[i].text):
                body.append(lines[i])
                i += 1
            if i >= len(lines):
                raise SyntaxError(f"строка {line.src_line_no}: незакрытый .macro")
            macros[name] = Macro(name=name, params=params, body=body)
            i += 1
            continue

        first_tok = text.split()[0]
        if first_tok in macros:
            macro = macros[first_tok]
            args = _split_operands(text[len(first_tok) :].strip())
            if len(args) != len(macro.params):
                raise SyntaxError(
                    f"строка {line.src_line_no}: макрос {macro.name} ждёт "
                    f"{len(macro.params)} аргумент(ов), получено {len(args)}"
                )
            substitution = dict(zip(macro.params, args, strict=False))
            for body_line in macro.body:
                expanded = _replace_tokens(body_line.text, substitution)
                expanded = _replace_tokens(expanded, constants)
                out.append(Line(text=expanded, src_line_no=line.src_line_no))
            i += 1
            continue

        out.append(Line(text=_replace_tokens(text, constants), src_line_no=line.src_line_no))
        i += 1

    if len(active) != 1:
        raise SyntaxError("условный блок .if не закрыт директивой .endif")
    return out


def _expand_pseudo(lines: list[Line]) -> list[Line]:
    """Развернуть псевдоинструкции, не помещающиеся в одно слово.

    """
    out: list[Line] = []
    for line in lines:
        text = line.text
        # отделяем возможную метку в начале
        prefix = ""
        body = text
        if ":" in text:
            idx = text.index(":")

            head = text[:idx].strip()
            if re.match(r"^\w+$", head):
                prefix = text[: idx + 1] + " "
                body = text[idx + 1 :].strip()

        parts = body.split(None, 1)
        if len(parts) == 2 and parts[0].upper() == "LI":
            operands = _split_operands(parts[1])
            if len(operands) == 2 and _is_plain_int(operands[1]):
                value = _parse_int(operands[1])
                lo16 = -(1 << (IMM16_BITS - 1))
                hi16 = (1 << (IMM16_BITS - 1)) - 1
                if not (lo16 <= value <= hi16):
                    rd = operands[0]
                    uval = value & 0xFFFFFFFF
                    hi = (uval >> 16) & 0xFFFF
                    lo = uval & 0xFFFF
                    out.append(Line(text=f"{prefix}LUI {rd}, {hi}", src_line_no=line.src_line_no))
                    out.append(Line(text=f"ORI {rd}, {rd}, {lo}", src_line_no=line.src_line_no))
                    continue
        out.append(line)
    return out


def _is_plain_int(token: str) -> bool:
    """True, если токен — числовой литерал (не метка)."""
    try:
        _parse_int(token)
        return True
    except ValueError:
        return False


_TOKEN_RE = re.compile(r"\b\w+\b")


def _replace_tokens(text: str, mapping: dict[str, str]) -> str:
    """Заменить «слова» в тексте по словарю. """
    if not mapping:
        return text

    def repl(m: re.Match[str]) -> str:
        return mapping.get(m.group(0), m.group(0))

    return _TOKEN_RE.sub(repl, text)


def _split_operands(operands: str) -> list[str]:
    """Поделить строку операндов по запятой, учитывая кавычки"""
    if not operands:
        return []
    parts: list[str] = []
    cur: list[str] = []
    in_quotes = False
    for ch in operands:
        if ch == '"':
            in_quotes = not in_quotes
            cur.append(ch)
        elif ch == "," and not in_quotes:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur).strip())
    return parts


# Парсинг операндов
_RE_REG = re.compile(r"^R(\d+)$", re.IGNORECASE)
_RE_VREG = re.compile(r"^V(\d+)$", re.IGNORECASE)
_RE_MEMREF = re.compile(r"^(-?\d+)\(R(\d+)\)$", re.IGNORECASE)


def _parse_int(text: str) -> int:
    """Распарсить целое в форматах: 10, -7, 0x1F, 0b1010, символ 'A'."""
    text = text.strip()
    if text.startswith("'") and text.endswith("'") and len(text) >= 3:
        # символьный литерал, например 'A'
        body = text[1:-1]
        if body == r"\n":
            return ord("\n")
        if body == r"\t":
            return ord("\t")
        if body == r"\0":
            return 0
        if body == r"\\":
            return ord("\\")
        if body == r"\'":
            return ord("'")
        if len(body) == 1:
            return ord(body)
        raise ValueError(f"неподдерживаемый символьный литерал: {text}")
    base = 10
    sign = 1
    s = text
    if s.startswith("-"):
        sign = -1
        s = s[1:]
    if s.lower().startswith("0x"):
        base = 16
        s = s[2:]
    elif s.lower().startswith("0b"):
        base = 2
        s = s[2:]
    return sign * int(s, base)


def _parse_reg(text: str) -> int:
    m = _RE_REG.match(text.strip())
    if not m:
        raise SyntaxError(f"ожидался регистр R0..R7, получено: {text!r}")
    idx = int(m.group(1))
    if not 0 <= idx < 8:
        raise SyntaxError(f"регистр R{idx} вне диапазона R0..R7")
    return idx


def _parse_vreg(text: str) -> int:
    m = _RE_VREG.match(text.strip())
    if not m:
        raise SyntaxError(f"ожидался векторный регистр V0..V3, получено: {text!r}")
    idx = int(m.group(1))
    if not 0 <= idx < 4:
        raise SyntaxError(f"векторный регистр V{idx} вне диапазона V0..V3")
    return idx


def _parse_memref(text: str) -> tuple[int, int]:
    """Парсит memref `imm(Rx)`, возвращает (imm, reg_index)."""
    m = _RE_MEMREF.match(text.strip())
    if not m:
        raise SyntaxError(f"ожидался memref вида `imm(Rn)`, получено: {text!r}")
    return int(m.group(1)), int(m.group(2))


# Транслятор
@dataclass
class Translator:
    labels: dict[str, int] = field(default_factory=dict)
    # Сюда  результа
    memory_image: dict[int, int] = field(default_factory=dict)
    # Для отладочного дампа сохраняем (addr, raw, mnemonic_text, src_line).
    debug_dump: list[tuple[int, int, str, str]] = field(default_factory=list)
    entry_point: int = PROGRAM_START_DEFAULT

    #  Первый проход
    def _first_pass(self, lines: list[Line]) -> list[tuple[int, Line]]:
        """Назначить адрес каждой строке, заполнить self.labels.

        Возвращает список (addr, line) — без меток-описаний и директив
        .org/.equ (они уже учтены).
        """
        addressed: list[tuple[int, Line]] = []
        # По умолчанию начинаем с PROGRAM_START_DEFAULT (байтовый адрес 4).
        # Адрес 0..3 зарезервирован под 32-битный вектор прерывания.
        current_addr = PROGRAM_START_DEFAULT
        for line in lines:
            text = line.text

            #  директивы секций

            if text in (".text", ".data"):
                continue

            #  .org N
            if text.lower().startswith(".org"):
                rest = text.split(None, 1)[1].strip()
                current_addr = _parse_int(rest)
                if not 0 <= current_addr <= MEMORY_SIZE - WORD_BYTES:
                    raise SyntaxError(
                        f"строка {line.src_line_no}: .org {current_addr} вне диапазона памяти"
                    )
                if current_addr % WORD_BYTES != 0:
                    raise SyntaxError(
                        f"строка {line.src_line_no}: .org {current_addr} не выровнен на слово "
                        f"({WORD_BYTES} байта)"
                    )
                continue

            #  метка
            if ":" in text:
                idx = text.index(":")
                label = text[:idx].strip()
                if not re.match(r"^\w+$", label):
                    raise SyntaxError(f"строка {line.src_line_no}: некорректная метка {label!r}")
                if label in self.labels:
                    raise SyntaxError(f"строка {line.src_line_no}: метка {label} уже определена")
                self.labels[label] = current_addr
                tail = text[idx + 1 :].strip()
                if not tail:
                    continue
                text = tail
                line = Line(text=text, src_line_no=line.src_line_no)

            #  директивы данных
            if text.lower().startswith(".word"):
                rest = text.split(None, 1)[1] if len(text.split(None, 1)) > 1 else ""
                values = _split_operands(rest)
                addressed.append(
                    (
                        current_addr,
                        Line(text=".word " + ",".join(values), src_line_no=line.src_line_no),
                    )
                )
                current_addr += len(values) * WORD_BYTES
                continue
            if text.lower().startswith(".string"):
                m = re.match(r'^\.string\s+"(.*)"\s*$', text)
                if not m:
                    raise SyntaxError(f"строка {line.src_line_no}: некорректный .string {text!r}")
                body = _decode_escapes(m.group(1))
                length = len(body)
                addressed.append(
                    (
                        current_addr,
                        Line(text=f'.string "{m.group(1)}"', src_line_no=line.src_line_no),
                    )
                )
                current_addr += (1 + length) * WORD_BYTES  # длина и символы — 32-битные слова
                continue

            #  обычная инструкция
            addressed.append((current_addr, Line(text=text, src_line_no=line.src_line_no)))
            current_addr += WORD_BYTES

            if current_addr > MEMORY_SIZE:
                raise SyntaxError(f"строка {line.src_line_no}: программа не помещается в память")

        return addressed

    #  Второй прохо
    def _second_pass(self, addressed: list[tuple[int, Line]]) -> None:
        """Закодировать каждую строку и положить в self.memory_image."""
        for addr, line in addressed:
            text = line.text
            # директивы данных
            if text.lower().startswith(".word"):
                rest = text.split(None, 1)[1]
                values = _split_operands(rest)
                for i, v in enumerate(values):
                    word = clip_word(self._resolve_value(v, line.src_line_no))
                    word_addr = addr + i * WORD_BYTES
                    self.memory_image[word_addr] = to_unsigned(word, 32)
                    self.debug_dump.append((word_addr, to_unsigned(word, 32), f".word {v}", text))
                continue
            if text.lower().startswith(".string"):
                m = re.match(r'^\.string\s+"(.*)"\s*$', text)
                assert m
                body = _decode_escapes(m.group(1))
                # 1) слово-длина (pstr)
                self.memory_image[addr] = to_unsigned(len(body), 32)
                self.debug_dump.append(
                    (addr, to_unsigned(len(body), 32), f".string len={len(body)}", text)
                )
                # 2) по одному коду на слово
                for i, ch in enumerate(body, start=1):
                    code = ord(ch)
                    word_addr = addr + i * WORD_BYTES
                    self.memory_image[word_addr] = code
                    self.debug_dump.append((word_addr, code, f".string '{_escape_char(ch)}'", text))
                continue
            # обычная инструкция
            word, mnem = self._encode_instruction(text, addr, line.src_line_no)
            self.memory_image[addr] = word
            self.debug_dump.append((addr, word, mnem, text))

    def _resolve_value(self, token: str, src_line_no: int) -> int:
        """Превратить токен в число: либо метка, либо литерал."""
        token = token.strip()
        if token in self.labels:
            return self.labels[token]
        try:
            return _parse_int(token)
        except ValueError as e:
            raise SyntaxError(
                f"строка {src_line_no}: не удаётся разобрать значение {token!r}"
            ) from e

    def _encode_instruction(self, text: str, addr: int, src_line_no: int) -> tuple[int, str]:
        """Закодировать одну инструкци"""
        parts = text.split(None, 1)
        op_name = parts[0].upper()
        operands_str = parts[1] if len(parts) > 1 else ""
        operands = _split_operands(operands_str)

        try:
            op = Opcode[op_name]
        except KeyError as e:
            raise SyntaxError(f"строка {src_line_no}: неизвестная инструкция {op_name}") from e

        #  R-тип
        if op in R_TYPE_OPCODES:
            if len(operands) != 3:
                raise SyntaxError(f"строка {src_line_no}: {op_name} ждёт 3 операнда")
            rd = _parse_reg(operands[0])
            rs1 = _parse_reg(operands[1])
            rs2 = _parse_reg(operands[2])
            word = encode(op, rd=rd, rs1=rs1, rs2=rs2)
            return word, mnemonic(decode(word))

        #  I-тип
        if op in I_TYPE_OPCODES:
            # LI Rd, imm    — 2 операнда
            if op in (Opcode.LI, Opcode.LUI):
                if len(operands) != 2:
                    raise SyntaxError(f"строка {src_line_no}: {op_name} ждёт 2 операнда")
                rd = _parse_reg(operands[0])
                imm = self._resolve_value(operands[1], src_line_no)
                # LUI работает с битовой маской (старшие 16 бит) — беззнаковый;
                # LI — обычная знаковая загрузка.
                imm = _check_imm(imm, IMM16_BITS, op_name, src_line_no, signed=(op == Opcode.LI))
                word = encode(op, rd=rd, imm=imm)
                return word, mnemonic(decode(word))

            # LW Rd, imm(Rs) / SW Rd, imm(Rs)
            if op in (Opcode.LW, Opcode.SW):
                if len(operands) != 2:
                    raise SyntaxError(f"строка {src_line_no}: {op_name} ждёт 2 операнда")
                rd = _parse_reg(operands[0])
                imm, rs1 = _parse_memref(operands[1])
                imm = _check_imm(imm, IMM16_BITS, op_name, src_line_no)
                word = encode(op, rd=rd, rs1=rs1, imm=imm)
                return word, mnemonic(decode(word))

            # BEQ/BNE/BLT/BGT/BLE/BGE
            if op in (Opcode.BEQ, Opcode.BNE, Opcode.BLT, Opcode.BGT, Opcode.BLE, Opcode.BGE):
                if len(operands) != 3:
                    raise SyntaxError(f"строка {src_line_no}: {op_name} ждёт 3 операнда")
                rd = _parse_reg(operands[0])
                rs1 = _parse_reg(operands[1])
                target = self._resolve_value(operands[2], src_line_no)
                # branch — относительный (PC-relative), адреса и смещение в байтах.
                offset = target - (addr + WORD_BYTES)
                offset = _check_imm(offset, IMM16_BITS, op_name, src_line_no)
                word = encode(op, rd=rd, rs1=rs1, imm=offset)
                return word, mnemonic(decode(word))

            # ADDI/SUBI/MULI/ANDI/ORI
            if len(operands) != 3:
                raise SyntaxError(f"строка {src_line_no}: {op_name} ждёт 3 операнда")
            rd = _parse_reg(operands[0])
            rs1 = _parse_reg(operands[1])
            imm = self._resolve_value(operands[2], src_line_no)
            imm = _check_imm(
                imm,
                IMM16_BITS,
                op_name,
                src_line_no,
                signed=(op not in (Opcode.ANDI, Opcode.ORI)),
            )
            word = encode(op, rd=rd, rs1=rs1, imm=imm)
            return word, mnemonic(decode(word))

        #  J-тип
        if op == Opcode.JMP:
            if len(operands) != 1:
                raise SyntaxError(f"строка {src_line_no}: JMP ждёт 1 операнд (адрес)")
            target = self._resolve_value(operands[0], src_line_no)
            imm = _check_imm(target, IMM20_BITS, "JMP", src_line_no)
            word = encode(op, imm=imm)
            return word, mnemonic(decode(word))
        if op == Opcode.JAL:
            if len(operands) != 2:
                raise SyntaxError(f"строка {src_line_no}: JAL ждёт 2 операнда")
            rd = _parse_reg(operands[0])
            target = self._resolve_value(operands[1], src_line_no)
            imm = _check_imm(target, IMM20_BITS, "JAL", src_line_no)
            word = encode(op, rd=rd, imm=imm)
            return word, mnemonic(decode(word))
        if op == Opcode.JR:
            if len(operands) != 1:
                raise SyntaxError(f"строка {src_line_no}: JR ждёт 1 операнд")
            rd = _parse_reg(operands[0])
            word = encode(op, rd=rd)
            return word, mnemonic(decode(word))

        #  V-тип
        if op in (Opcode.VADD, Opcode.VSUB, Opcode.VMUL, Opcode.VDIV, Opcode.VCMP):
            if len(operands) != 3:
                raise SyntaxError(f"строка {src_line_no}: {op_name} ждёт 3 векторных регистра")
            vd = _parse_vreg(operands[0])
            vs1 = _parse_vreg(operands[1])
            vs2 = _parse_vreg(operands[2])
            word = encode(op, rd=vd, rs1=vs1, rs2=vs2)
            return word, mnemonic(decode(word))
        if op in (Opcode.VLD, Opcode.VST):
            if len(operands) != 2:
                raise SyntaxError(f"строка {src_line_no}: {op_name} ждёт 2 операнда")
            vd = _parse_vreg(operands[0])
            imm, rs1 = _parse_memref(operands[1])
            imm = _check_imm(imm, IMM16_BITS, op_name, src_line_no)
            word = encode(op, rd=vd, rs1=rs1, imm=imm)
            return word, mnemonic(decode(word))
        if op == Opcode.VBC:
            if len(operands) != 2:
                raise SyntaxError(f"строка {src_line_no}: VBC ждёт 2 операнда")
            vd = _parse_vreg(operands[0])
            rs1 = _parse_reg(operands[1])
            word = encode(op, rd=vd, rs1=rs1)
            return word, mnemonic(decode(word))
        if op == Opcode.VRED:
            if len(operands) != 2:
                raise SyntaxError(f"строка {src_line_no}: VRED ждёт 2 операнда")
            rd = _parse_reg(operands[0])
            vs1 = _parse_vreg(operands[1])
            word = encode(op, rd=rd, rs1=vs1)
            return word, mnemonic(decode(word))

        # --- S-тип ---
        if op in S_TYPE_OPCODES:
            if operands:
                raise SyntaxError(f"строка {src_line_no}: {op_name} не принимает операнды")
            word = encode(op)
            return word, mnemonic(decode(word))

        raise SyntaxError(f"строка {src_line_no}: opcode {op_name} не обработан транслятором")

    #  API
    def translate(self, source: str) -> None:
        """Полный цикл: разбор + два прохода."""
        lines = _read_lines(source)
        lines = _preprocess(lines)
        lines = _expand_pseudo(lines)
        # извлекаем .entry, если есть, до первого прохода
        filtered: list[Line] = []
        for line in lines:
            if line.text.lower().startswith(".entry"):
                rest = line.text.split(None, 1)[1].strip()
                # сохраняем токен — разрешим во втором проходе
                self._entry_token = rest
                continue
            filtered.append(line)
        addressed = self._first_pass(filtered)
        self._second_pass(addressed)
        # резолвим entry
        token = getattr(self, "_entry_token", None)
        if token is not None:
            self.entry_point = self._resolve_value(token, 0)
        elif "_start" in self.labels:
            self.entry_point = self.labels["_start"]
        # иначе оставим PROGRAM_START_DEFAULT

    #  Сериализация бинарного файла
    def to_binary(self) -> bytes:
        out = bytearray()
        out += struct.pack("<I", self.entry_point)
        for addr in sorted(self.memory_image):
            out += struct.pack("<II", addr, self.memory_image[addr])
        return bytes(out)

    def to_debug_text(self) -> str:
        """Текстовый дамп для проверки человеком."""
        lines = [
            f"; entry point: {self.entry_point}",
            "; address - hex      - mnemonic                 - source",
        ]
        for addr, word, mnem, src in self.debug_dump:
            lines.append(f"{addr:04d} - {word:08X} - {mnem:<24s} - {src}")
        return "\n".join(lines) + "\n"


def _check_imm(value: int, bits: int, op_name: str, line_no: int, *, signed: bool = True) -> int:
    """Проверить, что immediate помещается
    """
    if signed:
        lo = -(1 << (bits - 1))
        hi = (1 << (bits - 1)) - 1
        if not lo <= value <= hi:
            raise SyntaxError(
                f"строка {line_no}: значение {value} не помещается "
                f"в {bits}-битный знаковый immediate инструкции {op_name}"
            )
        return value
    # беззнаковый случай
    if not 0 <= value <= (1 << bits) - 1:
        raise SyntaxError(
            f"строка {line_no}: значение {value} не помещается "
            f"в {bits}-битный беззнаковый immediate инструкции {op_name}"
        )
    # вернём то же битовое значение
    return to_signed(value, bits)


def _escape_char(ch: str) -> str:
    if ch == "\n":
        return "\\n"
    if ch == "\t":
        return "\\t"
    if ch == "\\":
        return "\\\\"
    return ch


def _decode_escapes(s: str) -> str:
    """Заменить escape-последовательности на реальные символы.
    """
    out: list[str] = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == "n":
                out.append("\n")
            elif nxt == "t":
                out.append("\t")
            elif nxt == "0":
                out.append("\0")
            elif nxt == "\\":
                out.append("\\")
            elif nxt == '"':
                out.append('"')
            else:
                out.append(c)
                out.append(nxt)
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


# Загрузка бинарного файла обратно
def load_binary(data: bytes) -> tuple[int, dict[int, int]]:
    """Прочитать бинарный файл, вернуть (entry_point, memory_image)."""
    if len(data) < 4:
        raise ValueError("файл слишком короткий")
    entry = struct.unpack_from("<I", data, 0)[0]
    pos = 4
    memory: dict[int, int] = {}
    while pos + 8 <= len(data):
        addr, word = struct.unpack_from("<II", data, pos)
        if addr % WORD_BYTES != 0 or addr > MEMORY_SIZE - WORD_BYTES:
            raise ValueError(f"некорректный байтовый адрес слова: {addr}")
        memory[addr] = word
        pos += 8
    if pos != len(data):
        raise ValueError("в файле остались лишние байты")
    return entry, memory



# CLI
def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Транслятор asm -> binary")
    parser.add_argument("source", help="входной asm файл")
    parser.add_argument("output", help="выходной бинарный файл")
    parser.add_argument("--listing", help="отладочный текстовый дамп", default=None)
    args = parser.parse_args(argv)

    with open(args.source, encoding="utf-8") as f:
        source = f.read()
    tr = Translator()
    try:
        tr.translate(source)
    except SyntaxError as e:
        print(f"Ошибка трансляции: {e}", file=sys.stderr)
        return 1

    with open(args.output, "wb") as f:
        f.write(tr.to_binary())
    if args.listing:
        with open(args.listing, "w", encoding="utf-8") as f:
            f.write(tr.to_debug_text())
    print(f"OK: {len(tr.memory_image)} слов записано в {args.output} (адреса байтовые)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
