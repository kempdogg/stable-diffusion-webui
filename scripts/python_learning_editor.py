"""Interactive Python learning editor for Windows users.

This module implements a lightweight integrated learning environment that
combines a text editor, runnable console, contextual help, curated examples,
and quiz widgets.  The user interface is powered by ``tkinter`` so it ships
with the standard CPython distribution on Windows.  To launch the editor run::

    python scripts/python_learning_editor.py

The application is intentionally self‑contained to make it easy for beginners
to explore Python without installing extra dependencies or IDEs.
"""

from __future__ import annotations

import io
import keyword
import textwrap
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from tkinter import (  # type: ignore[attr-defined]
    BOTH,
    END,
    LEFT,
    RIGHT,
    TOP,
    VERTICAL,
    Y,
    Event,
    Menu,
    Text,
    Tk,
    Toplevel,
)
from tkinter import filedialog, messagebox, ttk


@dataclass
class QuizQuestion:
    """Simple representation of a quiz question."""

    prompt: str
    answer: str
    explanation: str


class PythonLearningEditor:
    """Interactive text editor with built-in learning helpers.

    The implementation favours clarity over micro-optimisations so that the
    source code itself can serve as a learning resource for beginners who read
    through it.
    """

    AUTOCOMPLETE_SUGGESTIONS = sorted(
        set(keyword.kwlist)
        | {
            "print",
            "input",
            "range",
            "len",
            "enumerate",
            "list",
            "dict",
            "tuple",
            "set",
            "int",
            "float",
            "str",
            "open",
            "with",
            "for",
            "while",
            "def",
            "class",
            "import",
            "from",
        }
    )

    KEYWORD_HELP = {
        "for": "Iterate over items in a sequence. Syntax: for item in sequence:",
        "while": "Repeat a block while a condition remains True.",
        "def": "Define a function. Use parentheses for parameters.",
        "class": "Define a class that bundles data and behaviour.",
        "with": "Context manager for managing resources, e.g. files.",
        "print": "Display text or variables. Useful for debugging.",
        "import": "Bring modules or objects into the current namespace.",
        "list": "Mutable ordered collection. Use [] to define literals.",
        "dict": "Mapping of keys to values. Literal syntax uses {key: value}.",
    }

    CHEAT_SHEET = textwrap.dedent(
        """
        🐍 Python Cheat Sheet
        --------------------
        • print(value, ...): display output.
        • input(prompt): ask the user for data.
        • for item in sequence: iterate over items.
        • if condition: create decision branches.
        • list comprehensions: [expr for item in iterable].
        • with open('file.txt') as handle: manage file resources safely.
        • Modules are imported with `import math` or `from math import sqrt`.
        • Virtual environments keep project dependencies isolated.
        • Use `help(object)` in the console for built-in documentation.
        """
    ).strip()

    CODE_EXAMPLES = {
        "Hello": "print('Hello, Python adventurer!')",
        "FizzBuzz": textwrap.dedent(
            """
            for number in range(1, 21):
                if number % 15 == 0:
                    print('FizzBuzz')
                elif number % 3 == 0:
                    print('Fizz')
                elif number % 5 == 0:
                    print('Buzz')
                else:
                    print(number)
            """
        ).strip(),
        "Guess": textwrap.dedent(
            """
            import random

            secret = random.randint(1, 10)
            while True:
                guess = int(input('Guess between 1 and 10: '))
                if guess == secret:
                    print('You guessed it!')
                    break
                print('Too high!' if guess > secret else 'Too low!')
            """
        ).strip(),
    }

    QUIZ_QUESTIONS = (
        QuizQuestion(
            prompt="What keyword starts a function definition?",
            answer="def",
            explanation="Functions begin with the `def` keyword followed by the name.",
        ),
        QuizQuestion(
            prompt="Which built-in converts text to an integer?",
            answer="int",
            explanation="`int(value)` parses a string or number into an integer.",
        ),
        QuizQuestion(
            prompt="What statement lets you loop while a condition is true?",
            answer="while",
            explanation="Use `while condition:` to run a block until the condition fails.",
        ),
    )

    def __init__(self) -> None:
        self.root = Tk()
        self.root.title("Python Learning Editor")
        self.root.geometry("1200x720")

        self.file_path: Path | None = None
        self._build_layout()
        self._create_menus()
        self._bind_events()

        self._after_id: str | None = None
        self._autocomplete_window: Toplevel | None = None
        self._autocomplete_list: ttk.Treeview | None = None

    # ------------------------------------------------------------------ GUI --
    def _build_layout(self) -> None:
        container = ttk.PanedWindow(self.root, orient=VERTICAL)
        container.pack(fill=BOTH, expand=True)

        top_panel = ttk.PanedWindow(container, orient='horizontal')
        container.add(top_panel, weight=3)

        editor_frame = ttk.Frame(top_panel)
        top_panel.add(editor_frame, weight=3)

        text_scrollbar = ttk.Scrollbar(editor_frame)
        text_scrollbar.pack(side=RIGHT, fill=Y)

        self.line_numbers = Text(
            editor_frame,
            width=4,
            padx=4,
            takefocus=0,
            borderwidth=0,
            background="#f0f0f0",
            state="disabled",
        )
        self.line_numbers.pack(side=LEFT, fill=Y)

        self.text = Text(
            editor_frame,
            wrap="none",
            undo=True,
            font=("Consolas", 12),
        )
        self.text.pack(fill=BOTH, expand=True)
        self.text.config(yscrollcommand=lambda first, last: self._on_text_scroll(text_scrollbar, first, last))
        text_scrollbar.config(command=self._sync_scroll)

        helper_notebook = ttk.Notebook(top_panel, width=320)
        top_panel.add(helper_notebook, weight=1)

        self.helper_text = Text(helper_notebook, wrap="word", state="disabled")
        helper_notebook.add(self.helper_text, text="Helper")

        cheat_sheet = Text(helper_notebook, wrap="word", state="normal")
        cheat_sheet.insert("1.0", self.CHEAT_SHEET)
        cheat_sheet.config(state="disabled")
        helper_notebook.add(cheat_sheet, text="Cheat Sheet")

        examples_frame = ttk.Frame(helper_notebook)
        helper_notebook.add(examples_frame, text="Examples")
        self.example_list = ttk.Treeview(examples_frame, show="tree")
        self.example_list.pack(fill=BOTH, expand=True)
        for label in sorted(self.CODE_EXAMPLES):
            self.example_list.insert("", END, iid=label, text=label)

        quiz_frame = ttk.Frame(helper_notebook)
        helper_notebook.add(quiz_frame, text="Quiz")
        self.quiz_prompt = ttk.Label(quiz_frame, wraplength=260, justify=LEFT)
        self.quiz_prompt.pack(padx=8, pady=8, anchor='w')
        self.quiz_entry = ttk.Entry(quiz_frame)
        self.quiz_entry.pack(fill='x', padx=8)
        self.quiz_feedback = ttk.Label(quiz_frame, foreground="blue", wraplength=260)
        self.quiz_feedback.pack(padx=8, pady=(4, 8), anchor='w')
        self.quiz_button = ttk.Button(quiz_frame, text="Check", command=self._check_quiz)
        self.quiz_button.pack(padx=8, pady=(0, 8), anchor='e')
        self._quiz_index = 0
        self._show_quiz_question()

        console_frame = ttk.Frame(container)
        container.add(console_frame, weight=1)

        ttk.Label(console_frame, text="Console Output").pack(anchor='w')
        self.console = Text(console_frame, height=12, background="#1e1e1e", foreground="#d4d4d4")
        self.console.pack(fill=BOTH, expand=True)
        self.console.config(state="disabled")

        self.status = ttk.Label(self.root, text="Ready", anchor='w')
        self.status.pack(fill='x', side=TOP)

    def _create_menus(self) -> None:
        menubar = Menu(self.root)

        file_menu = Menu(menubar, tearoff=False)
        file_menu.add_command(label="New", accelerator="Ctrl+N", command=self.new_file)
        file_menu.add_command(label="Open...", accelerator="Ctrl+O", command=self.open_file)
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self.save_file)
        file_menu.add_command(label="Save As...", command=self.save_file_as)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        edit_menu = Menu(menubar, tearoff=False)
        edit_menu.add_command(label="Undo", accelerator="Ctrl+Z", command=self._undo)
        edit_menu.add_command(label="Redo", accelerator="Ctrl+Y", command=self._redo)
        edit_menu.add_separator()
        edit_menu.add_command(label="Find", accelerator="Ctrl+F", command=self._open_find_dialog)
        edit_menu.add_command(label="Clear Output", command=self.clear_console)
        menubar.add_cascade(label="Edit", menu=edit_menu)

        run_menu = Menu(menubar, tearoff=False)
        run_menu.add_command(label="Run Script", accelerator="F5", command=self.run_code)
        run_menu.add_command(label="Run Selection", accelerator="Shift+F5", command=self.run_selection)
        menubar.add_cascade(label="Run", menu=run_menu)

        help_menu = Menu(menubar, tearoff=False)
        help_menu.add_command(label="Python Tips", command=self._show_tips)
        help_menu.add_command(label="About", command=self._show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)

    def _bind_events(self) -> None:
        self.text.bind("<KeyRelease>", self._on_text_change)
        self.text.bind("<ButtonRelease>", self._update_helper_panel)
        self.text.bind("<Control-space>", self._show_autocomplete)
        self.text.bind("<Motion>", self._update_status_bar)
        self.text.bind("<KeyRelease>", self._update_status_bar)
        self.text.bind("<<Selection>>", self._update_helper_panel)
        self.text.bind("<F5>", lambda event: self._run_event(self.run_code))
        self.text.bind("<Shift-F5>", lambda event: self._run_event(self.run_selection))
        self.text.bind("<Control-n>", lambda event: self._run_event(self.new_file))
        self.text.bind("<Control-o>", lambda event: self._run_event(self.open_file))
        self.text.bind("<Control-s>", lambda event: self._run_event(self.save_file))
        self.text.bind("<Control-f>", lambda event: self._run_event(self._open_find_dialog))

        self.example_list.bind("<<TreeviewSelect>>", self._insert_example)

    # ---------------------------------------------------------- Event helpers --
    def _run_event(self, action: Callable[[], None]) -> str:
        action()
        return "break"

    def _on_text_change(self, event: Event | None = None) -> None:
        self._update_line_numbers()
        self._update_helper_panel()
        if self._after_id:
            self.root.after_cancel(self._after_id)
        self._after_id = self.root.after(200, self._highlight_syntax)

    def _update_status_bar(self, event: Event | None = None) -> None:
        line, column = self._cursor_position()
        filename = self.file_path.name if self.file_path else "Untitled"
        self.status.config(text=f"{filename} — line {line}, column {column}")

    def _cursor_position(self) -> tuple[int, int]:
        index = self.text.index("insert").split(".")
        return int(index[0]), int(index[1]) + 1

    # ----------------------------------------------------------- Line numbers --
    def _update_line_numbers(self) -> None:
        lines = int(self.text.index("end-1c").split(".")[0])
        content = "\n".join(str(number) for number in range(1, lines + 1))
        self.line_numbers.config(state="normal")
        self.line_numbers.delete("1.0", END)
        self.line_numbers.insert("1.0", content)
        self.line_numbers.config(state="disabled")

    def _sync_scroll(self, *args: str) -> None:
        self.text.yview(*args)
        self.line_numbers.yview(*args)

    def _on_text_scroll(self, scrollbar: ttk.Scrollbar, first: str, last: str) -> None:
        scrollbar.set(first, last)
        self.line_numbers.yview_moveto(first)

    # ----------------------------------------------------------- Syntax colour --
    def _highlight_syntax(self) -> None:
        self._after_id = None
        keyword_tag = "keyword"
        string_tag = "string"
        comment_tag = "comment"
        for tag in (keyword_tag, string_tag, comment_tag):
            self.text.tag_delete(tag)
        self.text.tag_configure(keyword_tag, foreground="#005cc5", font=("Consolas", 12, "bold"))
        self.text.tag_configure(string_tag, foreground="#a31515")
        self.text.tag_configure(comment_tag, foreground="#008000")

        content = self.text.get("1.0", "end-1c")
        for kw in keyword.kwlist:
            start = "1.0"
            while True:
                start = self.text.search(rf"\m{kw}\M", start, stopindex=END, regexp=True)
                if not start:
                    break
                end = f"{start}+{len(kw)}c"
                self.text.tag_add(keyword_tag, start, end)
                start = end

        start = "1.0"
        while True:
            start = self.text.search(r"(#.*)$", start, stopindex=END, regexp=True)
            if not start:
                break
            line_end = f"{start.split('.')[0]}.end"
            self.text.tag_add(comment_tag, start, line_end)
            start = line_end

        start = "1.0"
        while True:
            start = self.text.search(r"(['\"])(?:(?=(\\?))\2.)*?\1", start, stopindex=END, regexp=True)
            if not start:
                break
            end_index = self.text.index(f"{start}+1c")
            quote = self.text.get(start, end_index)
            end = self.text.search(quote, f"{start}+1c", regexp=False, stopindex=END)
            if not end:
                break
            end = self.text.index(f"{end}+1c")
            self.text.tag_add(string_tag, start, end)
            start = end

    # --------------------------------------------------------- Helper panels --
    def _update_helper_panel(self, event: Event | None = None) -> None:
        word = self._current_word()
        description = self.KEYWORD_HELP.get(word, "Select a keyword to see a tip.")
        self.helper_text.config(state="normal")
        self.helper_text.delete("1.0", END)
        self.helper_text.insert("1.0", description)
        self.helper_text.config(state="disabled")

    def _current_word(self) -> str:
        selection = self.text.get("sel.first", "sel.last") if self.text.tag_ranges("sel") else None
        if selection:
            return selection.strip()
        index = self.text.index("insert")
        line, column = map(int, index.split("."))
        start = f"{line}.{column} wordstart"
        end = f"{line}.{column} wordend"
        return self.text.get(start, end).strip()

    def _insert_example(self, event: Event) -> None:
        selection = self.example_list.selection()
        if not selection:
            return
        code = self.CODE_EXAMPLES.get(selection[0])
        if not code:
            return
        self.text.delete("1.0", END)
        self.text.insert("1.0", code)
        self._update_line_numbers()
        self._highlight_syntax()

    # -------------------------------------------------------------- Quiz app --
    def _show_quiz_question(self) -> None:
        question = self.QUIZ_QUESTIONS[self._quiz_index]
        self.quiz_prompt.config(text=question.prompt)
        self.quiz_entry.delete(0, END)
        self.quiz_feedback.config(text="")

    def _check_quiz(self) -> None:
        question = self.QUIZ_QUESTIONS[self._quiz_index]
        answer = self.quiz_entry.get().strip().lower()
        if answer == question.answer.lower():
            self.quiz_feedback.config(text=f"✅ Correct! {question.explanation}")
            self._quiz_index = (self._quiz_index + 1) % len(self.QUIZ_QUESTIONS)
        else:
            self.quiz_feedback.config(text=f"❌ Not quite. {question.explanation}")
        self.root.after(2000, self._show_quiz_question)

    # -------------------------------------------------------------- Autocomplete --
    def _show_autocomplete(self, event: Event | None = None) -> str:
        if self._autocomplete_window:
            self._autocomplete_window.destroy()

        word = self._current_word()
        matches = [item for item in self.AUTOCOMPLETE_SUGGESTIONS if item.startswith(word)]
        if not matches:
            return "break"

        bbox = self.text.bbox("insert")
        if not bbox:
            return "break"
        x, y, width, height = bbox
        x += self.text.winfo_rootx()
        y += self.text.winfo_rooty() + height

        window = Toplevel(self.root)
        window.wm_overrideredirect(True)
        window.geometry(f"200x200+{x}+{y}")
        self._autocomplete_window = window

        tree = ttk.Treeview(window, show="tree")
        tree.pack(fill=BOTH, expand=True)
        for item in matches:
            tree.insert("", END, iid=item, text=item)
        tree.focus(matches[0])
        tree.selection_set(matches[0])
        tree.bind("<Double-1>", lambda e: self._insert_autocomplete(tree))
        tree.bind("<Return>", lambda e: self._insert_autocomplete(tree))
        tree.bind("<Escape>", lambda e: self._close_autocomplete())
        tree.focus_set()
        self._autocomplete_list = tree
        return "break"

    def _insert_autocomplete(self, tree: ttk.Treeview) -> None:
        selection = tree.selection()
        if not selection:
            return
        word = selection[0]
        self._replace_current_word(word)
        self._close_autocomplete()

    def _close_autocomplete(self) -> None:
        if self._autocomplete_window:
            self._autocomplete_window.destroy()
            self._autocomplete_window = None
        self._autocomplete_list = None

    def _replace_current_word(self, replacement: str) -> None:
        if self.text.tag_ranges("sel"):
            self.text.delete("sel.first", "sel.last")
            self.text.insert("insert", replacement)
        else:
            index = self.text.index("insert")
            line, column = map(int, index.split("."))
            start = f"{line}.{column} wordstart"
            end = f"{line}.{column} wordend"
            self.text.delete(start, end)
            self.text.insert(start, replacement)

    # --------------------------------------------------------------- File ops --
    def new_file(self) -> None:
        if self._confirm_unsaved_changes():
            self.text.delete("1.0", END)
            self.file_path = None
            self.status.config(text="Untitled — line 1, column 1")
            self.text.edit_modified(False)

    def open_file(self) -> None:
        if not self._confirm_unsaved_changes():
            return
        filename = filedialog.askopenfilename(filetypes=[("Python files", "*.py"), ("All files", "*.*")])
        if filename:
            path = Path(filename)
            self.text.delete("1.0", END)
            self.text.insert("1.0", path.read_text(encoding="utf8"))
            self.file_path = path
            self._update_line_numbers()
            self._highlight_syntax()
            self._update_status_bar()
            self.text.edit_modified(False)

    def save_file(self) -> None:
        if self.file_path is None:
            self.save_file_as()
            return
        self.file_path.write_text(self.text.get("1.0", "end-1c"), encoding="utf8")
        messagebox.showinfo("Saved", f"Saved to {self.file_path}")
        self.text.edit_modified(False)

    def save_file_as(self) -> None:
        filename = filedialog.asksaveasfilename(defaultextension=".py", filetypes=[("Python files", "*.py")])
        if filename:
            self.file_path = Path(filename)
            self.save_file()

    def _confirm_unsaved_changes(self) -> bool:
        if self.text.edit_modified():
            answer = messagebox.askyesnocancel("Unsaved changes", "Save the current file before proceeding?")
            if answer is None:
                return False
            if answer:
                self.save_file()
        self.text.edit_modified(False)
        return True

    def _undo(self) -> None:
        try:
            self.text.edit_undo()
        except Exception:
            pass

    def _redo(self) -> None:
        try:
            self.text.edit_redo()
        except Exception:
            pass

    def _open_find_dialog(self) -> None:
        dialog = Toplevel(self.root)
        dialog.title("Find text")
        dialog.transient(self.root)
        ttk.Label(dialog, text="Find:").pack(side=LEFT, padx=4, pady=4)
        entry = ttk.Entry(dialog)
        entry.pack(side=LEFT, padx=4, pady=4, fill='x', expand=True)
        entry.focus_set()

        def find_next() -> None:
            needle = entry.get()
            if not needle:
                return
            start = self.text.search(needle, self.text.index("insert"), stopindex=END)
            if start:
                end = f"{start}+{len(needle)}c"
                self.text.tag_remove("sel", "1.0", END)
                self.text.tag_add("sel", start, end)
                self.text.mark_set("insert", end)
                self.text.see(start)

        ttk.Button(dialog, text="Find", command=find_next).pack(side=RIGHT, padx=4, pady=4)
        dialog.bind("<Return>", lambda event: (find_next(), "break"))

    # ------------------------------------------------------------ Console ops --
    def clear_console(self) -> None:
        self.console.config(state="normal")
        self.console.delete("1.0", END)
        self.console.config(state="disabled")

    def run_code(self) -> None:
        code = self.text.get("1.0", "end-1c")
        self._execute_code(code)

    def run_selection(self) -> None:
        if not self.text.tag_ranges("sel"):
            messagebox.showinfo("No selection", "Select some code to run.")
            return
        code = self.text.get("sel.first", "sel.last")
        self._execute_code(code)

    def _execute_code(self, code: str) -> None:
        console_output = io.StringIO()
        console_error = io.StringIO()
        local_env: dict[str, object] = {}
        try:
            with redirect_stdout(console_output), redirect_stderr(console_error):
                exec(code, {"__name__": "__main__"}, local_env)
        except Exception as exc:
            console_error.write(f"Error: {exc}\n")
        finally:
            output = console_output.getvalue()
            errors = console_error.getvalue()
            self.console.config(state="normal")
            if output:
                self.console.insert(END, output)
            if errors:
                self.console.insert(END, errors)
            self.console.see(END)
            self.console.config(state="disabled")

    # --------------------------------------------------------------- Help menu --
    def _show_tips(self) -> None:
        tips = textwrap.dedent(
            """
            ✨ Productivity Tips
            --------------------
            • Press Ctrl+Space for autocomplete suggestions.
            • Use Shift+F5 to run only the selected portion of code.
            • Explore the Examples tab for curated snippets.
            • Keep an eye on the helper panel for keyword hints.
            • Experiment freely—the console output does not affect your files.
            """
        ).strip()
        messagebox.showinfo("Python Tips", tips)

    def _show_about(self) -> None:
        messagebox.showinfo(
            "About Python Learning Editor",
            "A friendly playground for experimenting with Python and learning the basics.",
        )

    # --------------------------------------------------------------- Lifecycle --
    def run(self) -> None:
        self._update_line_numbers()
        self._highlight_syntax()
        self.root.mainloop()


def main() -> None:
    editor = PythonLearningEditor()
    editor.run()


if __name__ == "__main__":
    main()

