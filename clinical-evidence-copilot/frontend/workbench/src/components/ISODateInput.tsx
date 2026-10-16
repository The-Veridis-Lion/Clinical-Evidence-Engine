import React, {useEffect, useRef} from 'react';

export function isoDateError(value: string, required = false): string {
  if (!value) return required ? 'Enter a date as YYYY-MM-DD.' : '';
  if (!/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value)) return 'Use YYYY-MM-DD, for example 2026-09-03.';
  const [year, month, day] = value.split('-').map(Number);
  // Round-trip the calendar components; Date.parse alone normalizes impossible
  // dates such as February 30 and treats some years inconsistently.
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  date.setUTCHours(0, 0, 0, 0);
  return year < 1 || date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day
    ? 'Enter a valid calendar date as YYYY-MM-DD.' : '';
}

export function ISODateInput({onChange, onInvalid, ...props}: Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'>) {
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (input.current) input.current.setCustomValidity(isoDateError(input.current.value, props.required));
  }, [props.value, props.required]);
  // Native date controls inherit the browser/OS locale even with lang="en".
  // Keep an explicit ISO input and validate dates without guessing or conversion.
  return <input {...props} ref={input} type="text" placeholder="YYYY-MM-DD" autoComplete="off" maxLength={10}
    onChange={event => {
      event.currentTarget.setCustomValidity(isoDateError(event.currentTarget.value, props.required));
      onChange?.(event);
    }} onInvalid={event => {
      event.currentTarget.setCustomValidity(isoDateError(event.currentTarget.value, props.required));
      onInvalid?.(event);
    }}/>;
}
