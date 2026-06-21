import React, { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';

interface Account {
  id: number;
  code: string;
  name: string;
  account_type?: string;
  balance_direction?: string;
}

interface AccountSelectProps {
  accounts: Account[];
  value: string;
  onChange: (code: string) => void;
  className?: string;
  placeholder?: string;
}

export default function AccountSelect({
  accounts,
  value,
  onChange,
  className = '',
  placeholder = '请选择科目编码或名称',
}: AccountSelectProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [searchTerm, setSearchTerm] = useState(value);
  const [dropdownStyle, setDropdownStyle] = useState<React.CSSProperties>({});
  const inputRef = useRef<HTMLInputElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setSearchTerm(value);
  }, [value]);

  const recalcPosition = useCallback(() => {
    if (inputRef.current) {
      const rect = inputRef.current.getBoundingClientRect();
      setDropdownStyle({
        position: 'fixed',
        top: rect.bottom + 4,
        left: rect.left,
        width: rect.width,
        zIndex: 9999,
      });
    }
  }, []);

  const open = useCallback(() => {
    setSearchTerm(value);
    setIsOpen(true);
    recalcPosition();
  }, [value, recalcPosition]);

  const close = useCallback(() => {
    setIsOpen(false);
    setSearchTerm(value);
  }, [value]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      const target = event.target as Node;
      const insideWrapper = wrapperRef.current?.contains(target);
      const insideDropdown = dropdownRef.current?.contains(target);
      if (!insideWrapper && !insideDropdown) {
        close();
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [close]);

  useEffect(() => {
    if (!isOpen) return;
    const onScroll = () => recalcPosition();
    window.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', onScroll);
    return () => {
      window.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', onScroll);
    };
  }, [isOpen, recalcPosition]);

  const filtered = accounts.filter(
    acc => acc.code.includes(searchTerm) || acc.name.includes(searchTerm)
  );

  const selectedAccount = accounts.find(acc => acc.code === value);
  const displayValue = !isOpen && selectedAccount
    ? `${selectedAccount.code} ${selectedAccount.name}`
    : searchTerm;

  const selectAccount = (code: string) => {
    setSearchTerm(code);
    onChange(code);
    close();
  };

  return (
    <div ref={wrapperRef} className="relative w-full">
      <input
        ref={inputRef}
        type="text"
        className={className}
        placeholder={placeholder}
        value={displayValue}
        onChange={(e) => {
          setSearchTerm(e.target.value);
          if (!isOpen) open();
        }}
        onFocus={() => {
          if (!isOpen) open();
        }}
      />
      {isOpen &&
        createPortal(
          <div ref={dropdownRef} style={dropdownStyle} className="bg-white border border-slate-200 shadow-lg rounded-lg max-h-60 overflow-auto">
            {filtered.length > 0 ? (
              filtered.map(acc => (
                <div
                  key={acc.id}
                  className="px-3 py-2 text-sm hover:bg-slate-50 cursor-pointer flex justify-between"
                  onMouseDown={(e) => {
                    e.preventDefault();
                    selectAccount(acc.code);
                  }}
                >
                  <span className="font-mono text-slate-600">{acc.code}</span>
                  <span className="text-slate-800 truncate ml-2">{acc.name}</span>
                </div>
              ))
            ) : (
              <div className="px-3 py-2 text-sm text-slate-500 text-center">未找到匹配项</div>
            )}
          </div>,
          document.body
        )}
    </div>
  );
}
