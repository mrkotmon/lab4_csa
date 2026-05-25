; sort.asm — вводит последовательность цифр до LF, хранит как pstr и сортирует.
.equ IO_IN  8184
.equ IO_OUT 8188
.equ LF     10

.data
.org 0
    .word irq_handler
.org 2048
values: .word 0
        .word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0

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
    BEQ   R2, R3, sort_start
    ADDI  R2, R2, -48
    LI    R3, values
    LW    R4, 0(R3)
    MULI  R5, R4, 4
    ADD   R5, R5, R3
    ADDI  R5, R5, 4
    SW    R2, 0(R5)
    ADDI  R4, R4, 1
    SW    R4, 0(R3)
    IRET

sort_start:
    DI
    LI    R2, values
    LW    R2, 0(R2)     ; length
    LI    R1, 0         ; outer i
outer:
    BGE   R1, R2, print
    LI    R3, 0         ; inner j
    SUBI  R4, R2, 1
    SUB   R4, R4, R1
inner:
    BGE   R3, R4, outer_next
    LI    R5, values
    ADDI  R5, R5, 4
    MULI  R6, R3, 4
    ADD   R5, R5, R6
    LW    R6, 0(R5)
    LW    R7, 4(R5)
    BLE   R6, R7, no_swap
    SW    R7, 0(R5)
    SW    R6, 4(R5)
no_swap:
    ADDI  R3, R3, 1
    JMP   inner
outer_next:
    ADDI  R1, R1, 1
    JMP   outer

print:
    LI    R3, 0
    LI    R4, IO_OUT
print_loop:
    BGE   R3, R2, newline
    LI    R5, values
    ADDI  R5, R5, 4
    MULI  R6, R3, 4
    ADD   R5, R5, R6
    LW    R6, 0(R5)
    ADDI  R6, R6, 48
    SW    R6, 0(R4)
    ADDI  R3, R3, 1
    JMP   print_loop
newline:
    LI    R6, LF
    SW    R6, 0(R4)
    HLT
