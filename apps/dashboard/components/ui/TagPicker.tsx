"use client";

import { useMemo, useState } from "react";

type TagPickerProps = {
  label: string;
  options: string[];
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
};

type MultiTagPickerProps = {
  label: string;
  options: string[];
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
};

function matchingOptions(options: string[], query: string, selected: string[] = []) {
  const normalizedQuery = query.trim().toLowerCase();
  return options
    .filter((option) => !selected.includes(option))
    .filter((option) => !normalizedQuery || option.toLowerCase().includes(normalizedQuery))
    .slice(0, 50);
}

export function TagPicker({ label, options, value, onChange, placeholder = "Search tags" }: TagPickerProps) {
  const [query, setQuery] = useState(value);
  const [open, setOpen] = useState(false);
  const matches = useMemo(() => matchingOptions(options, query), [options, query]);

  function selectTag(tag: string) {
    onChange(tag);
    setQuery(tag);
    setOpen(false);
  }

  return (
    <label className="tagPickerField">
      <span>{label}</span>
      <div className="tagPicker">
        <input
          value={query}
          placeholder={placeholder}
          onChange={(event) => {
            setQuery(event.target.value);
            onChange(event.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => window.setTimeout(() => setOpen(false), 150)}
        />
        {open ? (
          <div className="tagMenu">
            {matches.length ? (
              matches.map((option) => (
                <button className={option === value ? "tagOption selected" : "tagOption"} key={option} type="button" onMouseDown={() => selectTag(option)}>
                  {option}
                </button>
              ))
            ) : (
              <div className="tagOption emptyOption">No matching tags</div>
            )}
          </div>
        ) : null}
      </div>
    </label>
  );
}

export function MultiTagPicker({ label, options, value, onChange, placeholder = "Search tags" }: MultiTagPickerProps) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const matches = useMemo(() => matchingOptions(options, query, value), [options, query, value]);

  function addTag(tag: string) {
    if (!value.includes(tag)) {
      onChange([...value, tag]);
    }
    setQuery("");
    setOpen(true);
  }

  function removeTag(tag: string) {
    onChange(value.filter((current) => current !== tag));
  }

  function addTypedTag() {
    const typedTag = query.trim();
    if (typedTag && !value.includes(typedTag)) {
      onChange([...value, typedTag]);
      setQuery("");
    }
  }

  return (
    <label className="tagPickerField">
      <span>{label}</span>
      <div className="multiTagPicker">
        <div className="selectedTags">
          {value.map((tag) => (
            <button className="selectedTag" key={tag} type="button" onClick={() => removeTag(tag)}>
              {tag} x
            </button>
          ))}
          <input
            value={query}
            placeholder={placeholder}
            onChange={(event) => {
              setQuery(event.target.value);
              setOpen(true);
            }}
            onFocus={() => setOpen(true)}
            onBlur={() => window.setTimeout(() => setOpen(false), 150)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === ",") {
                event.preventDefault();
                addTypedTag();
              }
              if (event.key === "Backspace" && !query && value.length) {
                removeTag(value[value.length - 1]);
              }
            }}
          />
        </div>
        {open ? (
          <div className="tagMenu">
            {matches.length ? (
              matches.map((option) => (
                <button className="tagOption" key={option} type="button" onMouseDown={() => addTag(option)}>
                  {option}
                </button>
              ))
            ) : (
              <div className="tagOption emptyOption">No matching tags</div>
            )}
          </div>
        ) : null}
      </div>
    </label>
  );
}
