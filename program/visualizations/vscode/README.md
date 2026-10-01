# Luminal SSA syntax highlighting

> NOTE: this was written by AI with minimal review.

This local VS Code extension recognizes `.ssa` files and highlights the `ssa-v1`
header, section markers, names, constants, operators, splat, ternary selection,
full-line comments, and JSON buffers/cases/metadata. It provides bracket matching,
auto-closing pairs, and the line-comment shortcut. Inline program comments are
marked invalid. Colors follow the active editor theme.

## Install locally on macOS

From the repository root, use `.vscode` for VS Code or set `VSCODE=.cursor`
for Cursor (or another editor's directory name under your home directory):

```sh
VSCODE="${VSCODE:-.vscode}"
mkdir -p "$HOME/$VSCODE/extensions"
ln -s "$PWD/program/visualizations/vscode" "$HOME/$VSCODE/extensions/local.luminal-ssa-0.1.0"
```

Then run **Developer: Reload Window** in your editor and open any `programs/ssa/*.ssa`
file. The language mode should be **Luminal SSA**. This is a local installation;
it does not publish anything or require installing Node dependencies. Keep the
repository checkout available while using the symlink. To remove this local
installation, remove the symlink and reload your editor.

Alternatively, preview without installing using the VS Code CLI:

```sh
code --extensionDevelopmentPath="$PWD/program/visualizations/vscode" "$PWD/programs/ssa/03_vector_axpy.ssa"
```

The extension is declarative: no runtime JavaScript, language server, or build
step is needed. The key files are:

- `package.json`: registers the language and `.ssa` file association.
- `syntaxes/ssa.tmLanguage.json`: TextMate syntax grammar.
- `language-configuration.json`: comments and bracket configuration.

The grammar follows the [VS Code syntax-highlighting extension format](https://code.visualstudio.com/api/language-extensions/syntax-highlight-guide).
It highlights syntax; use the Python converter for validation and type errors.
Use **Developer: Inspect Editor Tokens and Scopes** to inspect highlighting.

## Test the grammar

From the repository root (Node.js 18+):

```sh
npm ci --prefix program/visualizations/vscode
npm test --prefix program/visualizations/vscode
```

These tests run the actual TextMate/Oniguruma tokenizer against the repository's
`.ssa` examples and focused highlighting fixtures, without launching VS Code.
