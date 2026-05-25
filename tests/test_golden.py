"""Golden-тесты для нашей инструментальной цепочки.

Каждый кейс — пара (программа на ASM, [файл с расписанием ввода]).
Тест транслирует программу, запускает на модели и сравнивает:
    - финальный вывод (stdout процессора, текстом);
    - количество тактов (нестрого, в пределах ±10% — чтобы случайные
      изменения в логике не ломали тест, но крупная регрессия ловилась).

Эталоны хранятся в tests/golden/*.out (текст вывода) и
tests/golden/*.meta (число тактов).  Если эталона нет — тест его
создаёт (используется при первом запуске или после намеренного
изменения).  Установите переменную окружения UPDATE_GOLDEN=1 чтобы
принудительно обновить эталоны.

Так как тесты импортируют наш транслятор и модель, добавим src/ в
sys.path.
"""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
EXAMPLES = ROOT / "examples"
GOLDEN = ROOT / "tests" / "golden"
sys.path.insert(0, str(SRC))

from machine import InputSchedule, Processor  # noqa: E402
from translator import Translator  # noqa: E402

# (имя теста, файл с asm, файл с json расписанием ввода или None)
CASES: list[tuple[str, str, str | None]] = [
    ("hello", "hello.asm", None),
    ("cat", "cat.asm", "cat_input.json"),
    ("hello_user_name", "hello_user_name.asm", "hello_user_name_input.json"),
    ("sort", "sort.asm", "sort_input.json"),
    ("double_precision", "double_precision.asm", None),
    ("bigconst", "bigconst.asm", None),
    ("prob6_scalar", "prob6_scalar.asm", None),
    ("prob6_vector", "prob6_vector.asm", None),
]

UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"


@pytest.fixture(autouse=True)
def _chdir(monkeypatch: pytest.MonkeyPatch) -> None:
    # тесты не зависят от cwd, но иногда удобно
    monkeypatch.chdir(ROOT)


@pytest.mark.parametrize(("name", "asm", "stdin_json"), CASES, ids=[c[0] for c in CASES])
def test_golden(name: str, asm: str, stdin_json: str | None) -> None:
    """Транслирует, симулирует и сравнивает вывод с эталоном."""
    # 1) Трансляция
    source = (EXAMPLES / asm).read_text(encoding="utf-8")
    tr = Translator()
    tr.translate(source)

    # 2) Подготовка ввода
    schedule: list[tuple[int, str]] = []
    if stdin_json is not None:
        schedule = [
            (int(t), str(c))
            for t, c in json.loads((EXAMPLES / stdin_json).read_text(encoding="utf-8"))
        ]

    # 3) Симуляция (журнал собираем в строку — позже берём представительную выжимку).
    log = io.StringIO()
    proc = Processor(
        dict(tr.memory_image.items()),
        tr.entry_point,
        input_schedule=InputSchedule(schedule),
        log_stream=log,
        max_ticks=200_000,
    )
    proc.run()

    output = "".join(chr(c) for c in proc.output_buffer)
    meta = {"ticks": proc.tick, "instructions": proc.instruction_count}
    log_excerpt = _excerpt_log(log.getvalue())

    out_path = GOLDEN / f"{name}.out"
    meta_path = GOLDEN / f"{name}.meta.json"
    log_path = GOLDEN / f"{name}.log"

    if UPDATE or not out_path.exists():
        GOLDEN.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        log_path.write_text(log_excerpt, encoding="utf-8")
        pytest.skip(f"эталон {name} создан/обновлён")

    expected_output = out_path.read_text(encoding="utf-8")
    assert output == expected_output, (
        f"\n--- эталон ---\n{expected_output}\n--- получено ---\n{output}"
    )

    expected_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    # допустимое отклонение по тактам — 0% (точная модель должна быть стабильной)
    assert meta["ticks"] == expected_meta["ticks"], (
        f"число тактов изменилось: было {expected_meta['ticks']}, стало {meta['ticks']}"
    )
    assert meta["instructions"] == expected_meta["instructions"]

    expected_log = log_path.read_text(encoding="utf-8")
    assert log_excerpt == expected_log, (
        "журнал отличается от эталонного (см. tests/golden/<name>.log)"
    )


def _excerpt_log(full_log: str, head: int = 40, tail: int = 40) -> str:
    """Берём первые `head` строк и последние `tail` строк журнала.

    Методичка запрещает класть в golden test журналы по сотне килобайт,
    но и отказываться от них целиком нельзя — нужна репрезентативная
    выжимка.  Голова показывает, как процессор стартует; хвост — как
    завершается.  Между ними вставляем маркер «пропущено».
    """
    lines = full_log.splitlines()
    if len(lines) <= head + tail:
        return full_log if full_log.endswith("\n") else full_log + "\n"
    skipped = len(lines) - head - tail
    pieces = [*lines[:head], f"... [пропущено {skipped} строк] ...", *lines[-tail:]]
    return "\n".join(pieces) + "\n"


def test_vector_beats_scalar() -> None:
    """Контрольный тест варианта `vector`: векторная версия должна быть
    быстрее скалярной по числу тактов на одинаковом N."""
    scalar_meta = json.loads((GOLDEN / "prob6_scalar.meta.json").read_text(encoding="utf-8"))
    vector_meta = json.loads((GOLDEN / "prob6_vector.meta.json").read_text(encoding="utf-8"))
    assert vector_meta["ticks"] < scalar_meta["ticks"], (
        "Векторная реализация не показала ускорения относительно скалярной "
        "— что-то не так с реализацией варианта."
    )
    speedup = scalar_meta["ticks"] / vector_meta["ticks"]
    assert speedup >= 1.5, f"Ускорение всего {speedup:.2f}× — мало"


def test_translator_rejects_bad_register() -> None:
    """Простой тест на ошибки: транслятор должен ругаться на R99."""
    tr = Translator()
    with pytest.raises(SyntaxError, match="регистр"):
        tr.translate("LI R99, 0\nHLT\n")


def test_translator_rejects_imm_overflow() -> None:
    """Транслятор отбрасывает immediate, не помещающийся в 16 бит.

    Для LI большие константы теперь разворачиваются (LUI+ORI), поэтому
    проверяем переполнение на ADDI, где разворота нет.
    """
    tr = Translator()
    with pytest.raises(SyntaxError, match="immediate"):
        tr.translate("ADDI R1, R0, 100000\nHLT\n")


def test_pstr_layout() -> None:
    """Pascal-string должен укладываться как [len, ch0, ch1, ...]."""
    tr = Translator()
    src = """
    .data
    .org 50
    s: .string "Hi"
    .text
    .org 1
    HLT
    """
    tr.translate(src)
    assert tr.memory_image[50] == 2  # длина
    assert tr.memory_image[51] == ord("H")
    assert tr.memory_image[52] == ord("i")


def test_roundtrip_binary() -> None:
    """Сериализация → загрузка → выполнение даёт тот же вывод."""
    from translator import load_binary

    source = (EXAMPLES / "hello.asm").read_text(encoding="utf-8")
    tr = Translator()
    tr.translate(source)
    binary = tr.to_binary()
    entry, memory = load_binary(binary)
    assert entry == tr.entry_point
    assert memory == tr.memory_image


def test_opcode_type_encoded_in_bits() -> None:
    """Тип инструкции должен читаться из старших 3 бит опкода.

    Это фиксирует ключевое свойство оптимизированного IR: декодеру не
    нужна таблица — формат определяется битами `opcode >> 5`.
    """
    import sys

    sys.path.insert(0, str(SRC))
    from isa import InstrType, Opcode, opcode_type

    assert opcode_type(int(Opcode.ADD)) == InstrType.R
    assert opcode_type(int(Opcode.ADDI)) == InstrType.I
    assert opcode_type(int(Opcode.JMP)) == InstrType.J
    assert opcode_type(int(Opcode.VADD)) == InstrType.V
    assert opcode_type(int(Opcode.VLD)) == InstrType.M
    assert opcode_type(int(Opcode.HLT)) == InstrType.S


def test_big_constant_expansion() -> None:
    """`LI Rd, BIG` должен развернуться в LUI+ORI и собрать верное значение."""
    tr = Translator()
    # 1000000 = 0x000F4240; hi=15, lo=16960
    tr.translate("LI R1, 1000000\nHLT\n")
    # первое слово — LUI R1, 15, второе — ORI R1, R1, 16960
    import sys

    sys.path.insert(0, str(SRC))
    from isa import Opcode, decode

    instr0 = decode(tr.memory_image[1])
    instr1 = decode(tr.memory_image[2])
    assert instr0.opcode == Opcode.LUI
    assert instr1.opcode == Opcode.ORI


def test_small_constant_not_expanded() -> None:
    """Маленькая константа остаётся одной инструкцией LI."""
    import sys

    sys.path.insert(0, str(SRC))
    from isa import Opcode, decode

    tr = Translator()
    tr.translate("LI R1, 42\nHLT\n")
    instr0 = decode(tr.memory_image[1])
    assert instr0.opcode == Opcode.LI
    assert instr0.imm == 42
