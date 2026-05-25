; Euler problem 6, vector. N вводится через trap; обрабатываются блоки по 4.
.equ IO_IN  8184
.equ IO_OUT 8188
.equ LF     10

.data
.org 0
    .word irq_handler
.org 2048
n_value: .word 0
lanes:   .word 1,2,3,4
digits:  .word 0,0,0,0,0,0,0,0,0,0,0,0

.text
.org 4
.entry _start
_start:
    EI
wait:
    JMP wait

irq_handler:
    LI    R1, IO_IN
    LW    R2, 0(R1)
    LI    R3, LF
    BEQ   R2, R3, calculate
    ADDI  R2, R2, -48
    LI    R3, n_value
    LW    R4, 0(R3)
    MULI  R4, R4, 10
    ADD   R4, R4, R2
    SW    R4, 0(R3)
    IRET

calculate:
    DI
    LI    R2, n_value
    LW    R2, 0(R2)     ; N from input
    LI    R3, lanes
    VLD   V0, 0(R3)     ; [1,2,3,4]
    LI    R6, 0
    VBC   V2, R6        ; vector sum accumulator
    VBC   V3, R6        ; vector square accumulator
    LI    R1, 0         ; already processed count
    SUBI  R3, R2, 3     ; block can begin while processed < N-3
vector_loop:
    BGE   R1, R3, reduce
    VBC   V1, R1
    VADD  V1, V1, V0   ; [processed+1 .. processed+4]
    VADD  V2, V2, V1
    VMUL  V1, V1, V1
    VADD  V3, V3, V1
    ADDI  R1, R1, 4
    JMP   vector_loop
reduce:
    VRED  R4, V2        ; scalar sum
    VRED  R5, V3        ; scalar sum of squares
remainder:
    ADDI  R1, R1, 1
    BGT   R1, R2, final
    ADD   R4, R4, R1
    MUL   R6, R1, R1
    ADD   R5, R5, R6
    JMP   remainder
final:
    MUL   R4, R4, R4
    SUB   R6, R4, R5
    JAL   R7, print_int
    LI    R1, LF
    LI    R2, IO_OUT
    SW    R1, 0(R2)
    HLT

print_int:
    LI    R3, 0
    LI    R4, digits
    LI    R5, 10
    BEQ   R6, R0, zero
extract:
    BEQ   R6, R0, emit
    MOD   R1, R6, R5
    DIV   R6, R6, R5
    ADDI  R1, R1, 48
    SW    R1, 0(R4)
    ADDI  R4, R4, 4
    ADDI  R3, R3, 1
    JMP   extract
zero:
    LI    R1, 48
    SW    R1, 0(R4)
    ADDI  R3, R3, 1
emit:
    LI    R2, IO_OUT
    LI    R5, digits
emit_loop:
    BEQ   R3, R0, emit_done
    ADDI  R3, R3, -1
    MULI  R1, R3, 4
    ADD   R1, R5, R1
    LW    R1, 0(R1)
    SW    R1, 0(R2)
    JMP   emit_loop
emit_done:
    JR    R7
