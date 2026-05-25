; ============================================================
;  prob6_vector.asm  --  векторная (vector) реализация Эйлера №6
;
;  Считает |sum(1..N)^2 - sum(1^2..N^2)|.
;  N кратно VECTOR_LEN (4) для простоты.
;
;  Алгоритм:
;     V_acc_sum   = [0,0,0,0]            ; векторный аккумулятор
;     V_acc_sq    = [0,0,0,0]
;     for blk = 0..N step 4:
;         V_x = MEM[arr + blk]           ; VLD: загрузить 4 числа
;         V_acc_sum += V_x               ; VADD: 4 элемента за такт ALU
;         V_acc_sq  += V_x * V_x         ; VMUL + VADD
;     sum    = VRED(V_acc_sum)
;     sum_sq = VRED(V_acc_sq)
;     result = sum*sum - sum_sq
;
;  Регистры:
;     R1 = смещение i в блоках по 4
;     R2 = N
;     R3 = base address (arr)
;     R4 = sum (после редукции)
;     R5 = sum_sq
;     R6 = scratch / result
;     V0 = текущий блок чисел
;     V1 = квадраты блока
;     V2 = аккумулятор суммы
;     V3 = аккумулятор квадратов
; ============================================================

.equ N      32              ; N кратно VECTOR_LEN=4
.equ IO_OUT 2047

.text
.org 1
_start:
        LI   R6, 0
        VBC  V2, R6             ; V2 = [0,0,0,0]
        VBC  V3, R6             ; V3 = [0,0,0,0]
        LI   R1, 0
        LI   R2, N
        LI   R3, arr

vloop:
        BGE  R1, R2, vdone
        ADD  R6, R3, R1
        VLD  V0, 0(R6)          ; V0 = [a, a+1, a+2, a+3]
        VMUL V1, V0, V0         ; V1 = поэлементные квадраты
        VADD V2, V2, V0         ; sum acc  += V0
        VADD V3, V3, V1         ; sumsq acc += V1
        ADDI R1, R1, 4
        JMP  vloop
vdone:
        VRED R4, V2             ; R4 = sum
        VRED R5, V3             ; R5 = sum_sq
        MUL  R4, R4, R4         ; R4 = sum*sum
        SUB  R6, R4, R5         ; R6 = result

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
.org 300
arr:    .word 1, 2, 3, 4, 5, 6, 7, 8
        .word 9, 10, 11, 12, 13, 14, 15, 16
        .word 17, 18, 19, 20, 21, 22, 23, 24
        .word 25, 26, 27, 28, 29, 30, 31, 32

.org 400
digits: .word 0,0,0,0,0,0,0,0,0,0,0,0
