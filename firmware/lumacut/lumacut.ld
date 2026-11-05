/* STM32F103RET6 behind the BTT bootloader: 512 KB flash, first 28 KB taken.
 * 484 KB are usable, but the image must stay below the self-update stage at
 * 0x08040000 and the contract caps it at 196 KB. */
EXTERN(vector_table)
ENTRY(reset_handler)

MEMORY
{
    rom (rx)  : ORIGIN = 0x08007000, LENGTH = 484K
    ram (rwx) : ORIGIN = 0x20000000, LENGTH = 64K
}

SECTIONS
{
    .text : {
        KEEP(*(.vectors))
        *(.text*)
        . = ALIGN(4);
        *(.rodata*)
        . = ALIGN(4);
    } >rom

    .preinit_array : {
        . = ALIGN(4);
        __preinit_array_start = .;
        KEEP(*(.preinit_array))
        __preinit_array_end = .;
    } >rom

    .init_array : {
        . = ALIGN(4);
        __init_array_start = .;
        KEEP(*(SORT(.init_array.*)))
        KEEP(*(.init_array))
        __init_array_end = .;
    } >rom

    .fini_array : {
        . = ALIGN(4);
        __fini_array_start = .;
        KEEP(*(.fini_array))
        KEEP(*(SORT(.fini_array.*)))
        __fini_array_end = .;
    } >rom

    .ARM.extab : { *(.ARM.extab*) } >rom
    .ARM.exidx : {
        __exidx_start = .;
        *(.ARM.exidx*)
        __exidx_end = .;
    } >rom

    . = ALIGN(4);
    _etext = .;

    /* .ramfunc is the flash self-copy routine: linked to RAM, stored in flash,
     * copied at start like any initialised data. */
    .data : {
        _data = .;
        *(.data*)
        . = ALIGN(4);
        *(.ramfunc*)
        . = ALIGN(4);
        _edata = .;
    } >ram AT >rom
    _data_loadaddr = LOADADDR(.data);

    .bss : {
        *(.bss*)
        *(COMMON)
        . = ALIGN(4);
        _ebss = .;
    } >ram

    /* Survives a reset: tells the next start that a fault handler ran. */
    .noinit (NOLOAD) : {
        *(.noinit*)
        . = ALIGN(4);
    } >ram

    /DISCARD/ : { *(.eh_frame) }

    . = ALIGN(4);
    end = .;
    /* Vector table value only: the same as the Marlin RC image the BTT bootloader
     * already started on this board. reset_handler then uses all of the RAM. */
    _stack = ORIGIN(ram) + 48K;
    _stack_top = ORIGIN(ram) + LENGTH(ram);

    ASSERT(LOADADDR(.data) + SIZEOF(.data) - ORIGIN(rom) <= 196K, "image above 196 KB, contract limit")
    ASSERT(_stack_top - end >= 8K, "less than 8 KB left for the stack")
}
