"""Интеграционные golden-тесты инструментальной цепочки ASM -> BIN -> CPU.

Для каждого алгоритма эталон содержит настоящий бинарный файл, листинг,
вывод, число тактов/инструкций и репрезентативную выжимку тактового журнала.
Входные расписания находятся рядом с исходниками в ``examples/*.json``.
"""

from __future__ import annotations

import io
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
EXAMPLES = ROOT / "examples"
GOLDEN = ROOT / "tests" / "golden"
sys.path.insert(0, str(SRC))

from isa import WORD_BYTES, InstrType, Opcode, decode, opcode_type  # noqa: E402
from machine import InputSchedule, Processor, Stage  # noqa: E402
from translator import Translator, load_binary  # noqa: E402


@dataclass(frozen=True)
class Case:
    name: str
    asm: str
    input_json: str | None = None


CASES = [
    Case("hello", "hello.asm"),
    Case("cat", "cat.asm", "cat_input.json"),
    Case("hello_user_name", "hello_user_name.asm", "hello_user_name_input.json"),
    Case("sort", "sort.asm", "sort_input.json"),
    Case("double_precision", "double_precision.asm"),
    Case("bigconst", "bigconst.asm"),
    Case("vector_ops", "vector_ops.asm"),
    Case("trap_overrun", "trap_overrun.asm", "trap_overrun_input.json"),
    Case("prob6_scalar", "prob6_scalar.asm", "prob6_input.json"),
    Case("prob6_vector", "prob6_vector.asm", "prob6_input.json"),
]
UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"


def _read_schedule(filename: str | None) -> list[tuple[int, str]]:
    if filename is None:
        return []
    source = json.loads((EXAMPLES / filename).read_text(encoding="utf-8"))
    return [(int(tick), str(char)) for tick, char in source]


def _translate_and_run(case: Case) -> tuple[Translator, Processor, str]:
    tr = Translator()
    tr.translate((EXAMPLES / case.asm).read_text(encoding="utf-8"))
    # Исполняем именно сериализованный бинарный образ, а не внутреннюю
    # структуру транслятора: так golden-тест покрывает полный toolchain.
    entry, memory = load_binary(tr.to_binary())
    log = io.StringIO()
    proc = Processor(
        memory,
        entry,
        InputSchedule(_read_schedule(case.input_json)),
        log_stream=log,
        max_ticks=500_000,
    )
    proc.run()
    assert proc.stage == Stage.HALTED
    return tr, proc, log.getvalue()


def _excerpt_log(full_log: str, head: int = 40, tail: int = 40) -> str:
    lines = full_log.splitlines()
    if len(lines) <= head + tail:
        return full_log if full_log.endswith("\n") else full_log + "\n"
    skipped = len(lines) - head - tail
    return "\n".join([*lines[:head], f"... [пропущено {skipped} строк] ...", *lines[-tail:]]) + "\n"


@pytest.mark.parametrize("case", CASES, ids=[case.name for case in CASES])
def test_golden(case: Case) -> None:
    tr, proc, full_log = _translate_and_run(case)
    output = "".join(chr(code) for code in proc.output_buffer)
    meta = {
        "ticks": proc.tick,
        "instructions": proc.instruction_count,
        "input_overruns": proc.input_overrun_count,
    }
    expected_files: dict[str, bytes | str] = {
        ".bin": tr.to_binary(),
        ".lst": tr.to_debug_text(),
        ".out": output,
        ".log": _excerpt_log(full_log),
        ".meta.json": json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
    }
    GOLDEN.mkdir(parents=True, exist_ok=True)
    for suffix, content in expected_files.items():
        path = GOLDEN / f"{case.name}{suffix}"
        if UPDATE:
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding="utf-8")
        assert path.exists(), f"Нет golden-файла {path}; запустите UPDATE_GOLDEN=1 pytest"
        actual = (
            path.read_bytes() if isinstance(content, bytes) else path.read_text(encoding="utf-8")
        )
        assert actual == content, f"Эталон {path.name} отличается от результата исполнения"


def test_vector_beats_scalar_on_same_trap_input() -> None:
    scalar = json.loads((GOLDEN / "prob6_scalar.meta.json").read_text(encoding="utf-8"))
    vector = json.loads((GOLDEN / "prob6_vector.meta.json").read_text(encoding="utf-8"))
    assert vector["ticks"] < scalar["ticks"]
    speedup = scalar["ticks"] / vector["ticks"]
    assert speedup >= 1.5, f"Ускорение недостаточно заметно: {speedup:.2f}x"


def test_pstr_layout_uses_byte_addresses() -> None:
    tr = Translator()
    tr.translate('.data\n.org 100\ns: .string "Hi"\n.text\n.org 4\nHLT\n')
    assert tr.memory_image[100] == 2
    assert tr.memory_image[100 + WORD_BYTES] == ord("H")
    assert tr.memory_image[100 + 2 * WORD_BYTES] == ord("i")
    assert 101 not in tr.memory_image


def test_unaligned_org_is_rejected() -> None:
    with pytest.raises(SyntaxError, match="не выровнен"):
        Translator().translate(".text\n.org 5\nHLT\n")


def test_conditional_compilation_and_macro() -> None:
    source = """
.equ ENABLE 1
.macro LOADX reg value
    LI reg, value
.endm
.text
.org 4
.if ENABLE
    LOADX R1, 65
.else
    LOADX R1, 66
.endif
HLT
"""
    tr = Translator()
    tr.translate(source)
    assert decode(tr.memory_image[4]).imm == 65


def test_roundtrip_binary_executes_same_program() -> None:
    case = Case("hello", "hello.asm")
    tr_direct = Translator()
    tr_direct.translate((EXAMPLES / case.asm).read_text(encoding="utf-8"))
    direct = Processor(tr_direct.memory_image, tr_direct.entry_point, max_ticks=100_000)
    direct.run()
    entry, memory = load_binary(tr_direct.to_binary())
    loaded = Processor(memory, entry, max_ticks=100_000)
    loaded.run()
    assert direct.output_buffer == loaded.output_buffer
    assert direct.tick == loaded.tick


def test_trap_has_one_word_port_without_hidden_queue() -> None:
    tr = Translator()
    tr.translate((EXAMPLES / "trap_overrun.asm").read_text(encoding="utf-8"))
    log = io.StringIO()
    proc = Processor(
        tr.memory_image,
        tr.entry_point,
        InputSchedule(_read_schedule("trap_overrun_input.json")),
        log_stream=log,
        max_ticks=1_000,
    )
    proc.run()
    assert proc.input_overrun_count == 1
    assert "INPUT OVERRUN" in log.getvalue()


def test_tick_limit_reports_failure() -> None:
    tr = Translator()
    tr.translate(".text\n.org 4\n_start: JMP _start\n")
    proc = Processor(tr.memory_image, tr.entry_point, max_ticks=20)
    with pytest.raises(RuntimeError, match="лимит тактов"):
        proc.run()


def test_opcode_type_encoded_in_bits() -> None:
    assert opcode_type(int(Opcode.ADD)) == InstrType.R
    assert opcode_type(int(Opcode.ADDI)) == InstrType.I
    assert opcode_type(int(Opcode.JMP)) == InstrType.J
    assert opcode_type(int(Opcode.VADD)) == InstrType.V
    assert opcode_type(int(Opcode.VLD)) == InstrType.M
    assert opcode_type(int(Opcode.HLT)) == InstrType.S


def test_big_constant_expansion() -> None:
    tr = Translator()
    tr.translate(".text\n.org 4\nLI R1, 1000000\nHLT\n")
    assert decode(tr.memory_image[4]).opcode == Opcode.LUI
    assert decode(tr.memory_image[4 + WORD_BYTES]).opcode == Opcode.ORI
