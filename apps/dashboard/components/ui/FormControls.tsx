import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

type FieldProps = {
  label: string;
  children: ReactNode;
};

export function Field({ label, children }: FieldProps) {
  return (
    <label>
      <span>{label}</span>
      {children}
    </label>
  );
}

export function TextInput({ label, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return (
    <Field label={label}>
      <input {...props} />
    </Field>
  );
}

export function TextArea({ label, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string }) {
  return (
    <Field label={label}>
      <textarea {...props} />
    </Field>
  );
}

export function SelectInput({ label, children, ...props }: SelectHTMLAttributes<HTMLSelectElement> & { label: string; children: ReactNode }) {
  return (
    <Field label={label}>
      <select {...props}>{children}</select>
    </Field>
  );
}

export function CheckboxField({ label, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return (
    <label className="checkboxLabel">
      <input type="checkbox" {...props} />
      <span>{label}</span>
    </label>
  );
}
