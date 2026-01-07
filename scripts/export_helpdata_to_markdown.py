#!/usr/bin/env python3
"""
Export Freeciv helpdata.txt to Markdown format.

This script parses the structured helpdata.txt file and converts it to a clean
markdown document suitable for documentation purposes.

Usage:
    python export_helpdata_to_markdown.py [--input PATH] [--output PATH]
"""

import argparse
import re
from pathlib import Path
from typing import Optional


def strip_i18n(text: str) -> str:
    """Remove i18n _("...") wrappers from text, preserving paragraph breaks."""
    # First, replace paragraph separators: "), _(" with a paragraph marker
    text = re.sub(r'"\s*\)\s*,\s*_\s*\(\s*"', '\n\n', text)
    text = re.sub(r"'\s*\)\s*,\s*_\s*\(\s*'", '\n\n', text)

    # Pattern matches _("content") or _('content')
    pattern = r'_\(\s*"((?:[^"\\]|\\.)*)"\s*\)|_\(\s*\'((?:[^\'\\]|\\.)*)\'\s*\)'

    def replace_i18n(match):
        return match.group(1) or match.group(2) or ''

    result = re.sub(pattern, replace_i18n, text, flags=re.DOTALL)
    return result


def clean_text(text: str) -> str:
    """Clean and format text for markdown."""
    # Remove line continuation backslashes
    text = text.replace('\\\n', '')

    # Handle explicit newlines
    text = text.replace('\\n', '\n')

    # Remove xgettext comments and other inline comments
    text = re.sub(r',?\s*;\s*/\*[^*]*\*/', '', text)

    # Remove trailing commas before newlines
    text = re.sub(r',\s*\n', '\n', text)

    # Clean up multiple spaces
    text = re.sub(r'  +', ' ', text)

    # Clean up leading/trailing whitespace per line
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(lines)

    # Remove empty lines at start/end
    text = text.strip()

    return text


def parse_helpdata(content: str) -> list[dict]:
    """Parse helpdata.txt content into structured sections."""
    sections = []
    current_section = None
    current_key = None
    current_value = []

    lines = content.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i]

        # Skip comments
        if line.strip().startswith(';'):
            i += 1
            continue

        # New section
        if line.startswith('[help_'):
            # Save previous section
            if current_section:
                if current_key and current_value:
                    current_section[current_key] = '\n'.join(current_value)
                sections.append(current_section)

            section_name = line[1:-1]  # Remove [ and ]
            current_section = {'id': section_name, 'name': None, 'text': None, 'generate': None}
            current_key = None
            current_value = []
            i += 1
            continue

        # Key = value
        if '=' in line and current_section:
            # Save previous key
            if current_key and current_value:
                current_section[current_key] = '\n'.join(current_value)

            key, _, value = line.partition('=')
            key = key.strip()
            value = value.strip()

            if key in ('name', 'text', 'generate', 'categories'):
                current_key = key
                current_value = [value]
            else:
                current_key = None
                current_value = []
            i += 1
            continue

        # Continuation of previous value
        if current_key and line.strip():
            current_value.append(line)

        i += 1

    # Don't forget the last section
    if current_section:
        if current_key and current_value:
            current_section[current_key] = '\n'.join(current_value)
        sections.append(current_section)

    return sections


def section_to_markdown(section: dict, level: int = 2) -> str:
    """Convert a section to markdown format."""
    lines = []

    # Determine section name and nesting level
    name = section.get('name', '')
    if name:
        name = strip_i18n(name)
        name = clean_text(name)
        # Remove ?help: prefix if present
        name = re.sub(r'^\?help:', '', name)

        # Count leading spaces for nesting (from original format)
        original_name = section.get('name', '')
        leading_spaces = len(original_name) - len(original_name.lstrip(' '))
        if '_(" ' in original_name or "_(' " in original_name:
            # Check inside the i18n wrapper
            match = re.search(r'_\(["\'](\s*)', original_name)
            if match:
                leading_spaces = len(match.group(1))

        # Adjust header level based on nesting
        header_level = level + (leading_spaces // 1) if leading_spaces else level
        header = '#' * min(header_level, 6)

        lines.append(f"{header} {name.strip()}")
        lines.append('')

    # Handle generate sections
    if section.get('generate'):
        gen_type = strip_i18n(section['generate']).strip()
        lines.append(f"> *This section is dynamically generated in-game from the {gen_type} ruleset data.*")
        lines.append('')
        return '\n'.join(lines)

    # Handle text content
    text = section.get('text', '')
    if text:
        text = strip_i18n(text)
        text = clean_text(text)

        # Split on double newlines (paragraph breaks)
        raw_paragraphs = re.split(r'\n\n+', text)

        for raw_para in raw_paragraphs:
            raw_para = raw_para.strip()
            if not raw_para:
                continue

            # Check if this is a table reference
            if raw_para.startswith('$'):
                table_name = raw_para[1:].strip().strip('"')
                lines.append(f"> *See in-game table: {table_name}*")
                lines.append('')
                continue

            # Check if this paragraph contains numbered/bulleted list items
            para_lines = raw_para.split('\n')
            in_list = False
            current_text = []

            for pline in para_lines:
                pline = pline.strip()
                if not pline:
                    continue

                # Check for list items
                if re.match(r'^[-*]\s', pline) or re.match(r'^\d+\.\s', pline):
                    # Flush any accumulated text first
                    if current_text:
                        lines.append(' '.join(current_text))
                        lines.append('')
                        current_text = []
                    lines.append(pline)
                    in_list = True
                elif in_list and pline and not pline[0].isupper():
                    # Continuation of list item (lowercase start)
                    if lines and lines[-1]:
                        lines[-1] += ' ' + pline
                else:
                    in_list = False
                    current_text.append(pline)

            if current_text:
                lines.append(' '.join(current_text))

            lines.append('')

    return '\n'.join(lines)


def generate_toc(sections: list[dict]) -> str:
    """Generate a table of contents from sections."""
    toc_lines = ['## Table of Contents', '']

    for section in sections:
        name = section.get('name', '')
        if not name:
            continue

        name = strip_i18n(name)
        name = clean_text(name)
        name = re.sub(r'^\?help:', '', name).strip()

        if not name:
            continue

        # Create anchor link
        anchor = name.lower()
        anchor = re.sub(r'[^a-z0-9\s-]', '', anchor)
        anchor = re.sub(r'\s+', '-', anchor)

        # Determine indentation
        original_name = section.get('name', '')
        indent = ''
        if '_(" ' in original_name or "_(' " in original_name:
            match = re.search(r'_\(["\'](\s+)', original_name)
            if match:
                indent = '  ' * len(match.group(1))

        toc_lines.append(f"{indent}- [{name}](#{anchor})")

    toc_lines.append('')
    return '\n'.join(toc_lines)


def convert_helpdata_to_markdown(input_path: Path, output_path: Path) -> None:
    """Main conversion function."""
    print(f"Reading: {input_path}")
    content = input_path.read_text(encoding='utf-8')

    print("Parsing helpdata sections...")
    sections = parse_helpdata(content)
    print(f"Found {len(sections)} sections")

    # Build markdown
    md_lines = [
        '# Freeciv Gameplay Rules',
        '',
        '> This document is extracted from `freeciv/freeciv/data/helpdata.txt` - the authoritative source for Freeciv game rules.',
        '> Some sections marked as "dynamically generated" contain content that is populated at runtime from the game\'s ruleset files.',
        '',
    ]

    # Add table of contents
    md_lines.append(generate_toc(sections))

    # Add horizontal rule before content
    md_lines.append('---')
    md_lines.append('')

    # Convert each section
    for section in sections:
        md_content = section_to_markdown(section)
        if md_content.strip():
            md_lines.append(md_content)

    # Write output
    output_content = '\n'.join(md_lines)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output_content, encoding='utf-8')
    print(f"Written: {output_path}")
    print(f"Total lines: {len(output_content.splitlines())}")


def main():
    parser = argparse.ArgumentParser(
        description='Export Freeciv helpdata.txt to Markdown format'
    )
    parser.add_argument(
        '--input', '-i',
        type=Path,
        default=Path(__file__).parent.parent / 'freeciv/freeciv/data/helpdata.txt',
        help='Path to helpdata.txt input file'
    )
    parser.add_argument(
        '--output', '-o',
        type=Path,
        default=Path(__file__).parent.parent / 'freeciv-web/src/main/webapp/docs/gameplay-rules.md',
        help='Path to output markdown file'
    )

    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: Input file not found: {args.input}")
        return 1

    convert_helpdata_to_markdown(args.input, args.output)
    return 0


if __name__ == '__main__':
    exit(main())
