; ============================================================
;  bigconst.asm  --  демонстрация разворота большой константы.
;
;  Число 1000000 не помещается в 16-битный immediate, поэтому
;  транслятор САМ разворачивает `LI R1, 1000000` в пару:
;        LUI R1, 15        ; старшие 16 бит (1000000 >> 16 = 15)
;        ORI R1, R1, 16960 ; младшие 16 бит (1000000 & 0xFFFF = 16960)
;
;  Программа выводит это число обратно, чтобы доказать, что
;  константа собрана верно: 15 * 65536 + 16960 = 1000000.
; ============================================================

.equ IO_OUT 2047

.text
.org 1
_start:
        LI   R6, 1000000        ; <- большая константа (развернётся транслятором)
        JAL  R7, print_int
        LI   R1, 10
        LI   R2, IO_OUT
        SW   R1, 0(R2)
        HLT

print_int:
        LI   R3, 0
        LI   R4, digits
        LI   R5, 10
        BEQ  R6, R0, pi_zero
pi_extract:
        BEQ  R6, R0, pi_print
        MOD  R1, R6, R5
        DIV  R6, R6, R5
        ADDI R1, R1, 48
        SW   R1, 0(R4)
        ADDI R4, R4, 1
        ADDI R3, R3, 1
        JMP  pi_extract
pi_zero:
        LI   R1, 48
        SW   R1, 0(R4)
        ADDI R3, R3, 1
pi_print:
        LI   R2, IO_OUT
        LI   R5, digits
pi_loop:
        BEQ  R3, R0, pi_done
        ADDI R3, R3, -1
        ADD  R1, R5, R3
        LW   R1, 0(R1)
        SW   R1, 0(R2)
        JMP  pi_loop
pi_done:
        JR   R7

.data
.org 200
digits: .word 0,0,0,0,0,0,0,0,0,0,0,0
