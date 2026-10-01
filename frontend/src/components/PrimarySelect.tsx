import { cn } from '@/lib/utils';
import { Select, type SelectProps } from '@mantine/core';
import React from 'react';

const PrimarySelect: React.FC<SelectProps> = ({
  className,
  classNames,
  styles,
  comboboxProps,
  ...rest
}) => {
  const parsedClassNames = classNames as Partial<Record<string, string>>;
  const stylesObj =
    typeof styles === 'object' && styles
      ? (styles as Record<string, React.CSSProperties>)
      : {};
  const inputStyles = stylesObj.input ?? {};
  const labelStyles = stylesObj.label ?? {};
  const dropdownStyles = stylesObj.dropdown ?? {};

  return (
    <Select
      className={cn(className)}
      maxDropdownHeight={145}
      comboboxProps={{
        shadow: 'md',
        transitionProps: { transition: 'fade', duration: 150 },
        ...comboboxProps,
      }}
      styles={{
        label: {
          marginBottom: '7.75px',
          ...labelStyles,
        },
        input: {
          background: '#FFFFFF00',
          color: 'var(--mantine-color-text-primary)',
          borderTop: '1px solid #FFFFFF1A',
          boxShadow:
            '0px -1px 0px 0px #00000026 inset, 0px 1px 0px 0px #FFFFFF0F inset',
          borderRadius: '32px',
          height: '38px',
          minHeight: '38px',
          ...inputStyles,
        },
        dropdown: {
          maxHeight: '180px',
          backdropFilter: 'blur(15px)',
          WebkitBackdropFilter: 'blur(15px)',
          backgroundColor: 'rgba(24, 24, 27, 0.75)',
          border: '1px solid rgba(255, 255, 255, 0.15)',
          borderRadius: '16px',
          padding: '6px',
          boxShadow: '0 8px 32px 0 rgba(0, 0, 0, 0.36)',
          ...dropdownStyles,
        },
      }}
      classNames={{
        ...parsedClassNames,
        dropdown: cn(
          'bg-primary-bg/40! backdrop-blur-[15px] border-primary-text/20 rounded-xl overflow-hidden shadow-xl',
          parsedClassNames?.dropdown
        ),
        option: cn(
          'text-secondary-text text-xs! py-2 px-3 rounded-lg transition-colors hover:bg-white/5! hover:text-primary-text! data-[selected]:bg-white/10! data-[selected]:text-primary-text! dark:hover:bg-white/5! light:hover:bg-black/5!',
          parsedClassNames?.option
        ),
      }}
      {...rest}
    />
  );
};

export default PrimarySelect;
