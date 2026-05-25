; ============================================================
;  prob6_scalar.asm
;  Задача Эйлера №6: |(1+2+...+N)^2 - (1^2+2^2+...+N^2)|
;
;  Скалярная реализация — для сравнения с векторной.
;  Массив 1..N лежит в .data статически (как и в векторной версии,
;  чтобы сравнение было честным).
;
;  Регистры:
;     R1 = i (индекс элемента)
;     R2 = N
;     R3 = base address
;     R4 = sum
;     R5 = sum_sq
;     R6 = временный / результат
;     R7 = link
; ============================================================

.equ N      32
.equ IO_OUT 2047

.text
.org 1
_start:
        LI   R1, 0          ; i = 0
        LI   R2, N
        LI   R3, arr
        LI   R4, 0          ; sum = 0
        LI   R5, 0          ; sq  = 0
loop:
        BGE  R1, R2, end    ; if i >= N: break
        ADD  R6, R3, R1     ; addr = arr + i
        LW   R6, 0(R6)      ; R6 = arr[i]
        ADD  R4, R4, R6     ; sum += arr[i]
        MUL  R6, R6, R6     ; R6 = arr[i]^2
        ADD  R5, R5, R6     ; sq += arr[i]^2
        ADDI R1, R1, 1
        JMP  loop
end:
        MUL  R4, R4, R4     ; R4 = sum*sum
        SUB  R6, R4, R5     ; R6 = sum*sum - sq

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
