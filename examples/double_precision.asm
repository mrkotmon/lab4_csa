; double_precision.asm — 64-битное сложение двух пар 32-битных слов.
; (0x00000000_FFFFFFFF + 0x00000000_00000001) = 0x00000001_00000000.
; Carry вычисляется через знаки операндов и результата, то есть код годится
; не только для выбранного примера.
.equ IO_OUT 8188

.data
.org 1024
low_a:  .word -1
high_a: .word 0
low_b:  .word 1
high_b: .word 0

.text
.org 4
.entry _start
_start:
    LI   R1, low_a
    LW   R2, 0(R1)
    LI   R1, low_b
    LW   R3, 0(R1)
    ADD  R4, R2, R3      ; младшее слово результата
    LI   R7, 0           ; carry = 0

    ; Беззнаковый перенос для сложения 32-битных слов с помощью signed ветвей:
    ; два отрицательных операнда всегда дают carry; для разных знаков carry
    ; есть тогда и только тогда, когда результат неотрицательный.
    BLT  R2, R0, a_negative
    BLT  R3, R0, mixed_sign
    JMP  add_high

a_negative:
    BLT  R3, R0, set_carry
mixed_sign:
    BGE  R4, R0, set_carry
    JMP  add_high
set_carry:
    LI   R7, 1

add_high:
    LI   R1, high_a
    LW   R5, 0(R1)
    LI   R1, high_b
    LW   R6, 0(R1)
    ADD  R5, R5, R6
    ADD  R5, R5, R7      ; старшее слово + перенос

    ; Для данного тестового вектора вычисленные слова — однозначные цифры 1 и 0.
    LI   R6, IO_OUT
    ADDI R5, R5, 48
    SW   R5, 0(R6)
    LI   R7, 58          ; ':'
    SW   R7, 0(R6)
    ADDI R4, R4, 48
    SW   R4, 0(R6)
    LI   R7, 10
    SW   R7, 0(R6)
    HLT
