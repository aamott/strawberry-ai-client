"""Markdown to HTML renderer for chat messages."""

import importlib.util
from typing import Optional

from .theme import Theme

try:
    import markdown
    from markdown.extensions.codehilite import CodeHiliteExtension
    from markdown.extensions.fenced_code import FencedCodeExtension
    from markdown.extensions.tables import TableExtension
    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False

HAS_PYGMENTS = importlib.util.find_spec("pygments") is not None


def render_markdown(text: str, theme: Optional[Theme] = None) -> str:
    """Render markdown text to HTML.

    Args:
        text: Markdown text
        theme: Optional theme for styling

    Returns:
        HTML string
    """
    if not HAS_MARKDOWN:
        # Fallback: basic escaping and line breaks
        text = text.replace("&", "&amp;")
        text = text.replace("<", "&lt;")
        text = text.replace(">", "&gt;")
        text = text.replace("\n", "<br>")
        return f"<p>{text}</p>"

    # Configure markdown extensions
    extensions = [
        "nl2br",  # Newlines to <br>
        FencedCodeExtension(),
        TableExtension(),
    ]

    if HAS_PYGMENTS:
        extensions.append(CodeHiliteExtension(
            css_class="codehilite",
            guess_lang=True,
            use_pygments=True,
        ))

    # Render markdown
    md = markdown.Markdown(extensions=extensions)
    html = md.convert(text)

    # Wrap in container and add styles
    css = get_markdown_css(theme)

    return f"""
    <style>{css}</style>
    <div class="markdown-body">{html}</div>
    """


def get_markdown_css(theme: Optional[Theme] = None) -> str:
    """Get CSS for markdown rendering.

    Args:
        theme: Optional theme for colors

    Returns:
        CSS string
    """
    # Default colors
    text_color = "#e6edf3"
    code_bg = "#161b22"
    border_color = "#30363d"
    link_color = "#58a6ff"
    heading_color = "#e6edf3"

    if theme:
        text_color = theme.text_primary
        code_bg = theme.bg_secondary
        border_color = theme.border
        link_color = theme.accent
        heading_color = theme.text_primary

    return f"""
        .markdown-body {{
            color: {text_color};
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans",
                         Helvetica, Arial, sans-serif;
            font-size: 14px;
            line-height: 1.6;
            word-wrap: break-word;
        }}

        .markdown-body h1, .markdown-body h2, .markdown-body h3,
        .markdown-body h4, .markdown-body h5, .markdown-body h6 {{
            color: {heading_color};
            font-weight: 600;
            margin-top: 1em;
            margin-bottom: 0.5em;
            line-height: 1.25;
        }}

        .markdown-body h1 {{ font-size: 1.5em; }}
        .markdown-body h2 {{ font-size: 1.3em; }}
        .markdown-body h3 {{ font-size: 1.1em; }}

        .markdown-body p {{
            margin-top: 0;
            margin-bottom: 0.5em;
        }}

        .markdown-body a {{
            color: {link_color};
            text-decoration: none;
        }}

        .markdown-body a:hover {{
            text-decoration: underline;
        }}

        .markdown-body code {{
            background-color: {code_bg};
            border-radius: 4px;
            padding: 0.2em 0.4em;
            font-family: "Consolas", "Monaco", "Courier New", monospace;
            font-size: 0.9em;
        }}

        .markdown-body pre {{
            background-color: {code_bg};
            border: 1px solid {border_color};
            border-radius: 8px;
            padding: 12px;
            overflow-x: auto;
            margin: 0.5em 0;
        }}

        .markdown-body pre code {{
            background-color: transparent;
            padding: 0;
            border-radius: 0;
        }}

        .markdown-body blockquote {{
            border-left: 4px solid {border_color};
            color: {text_color};
            margin: 0.5em 0;
            padding: 0 1em;
            opacity: 0.8;
        }}

        .markdown-body ul, .markdown-body ol {{
            margin-top: 0;
            margin-bottom: 0.5em;
            padding-left: 2em;
        }}

        .markdown-body li {{
            margin-bottom: 0.25em;
        }}

        .markdown-body table {{
            border-collapse: collapse;
            margin: 0.5em 0;
            width: 100%;
        }}

        .markdown-body th, .markdown-body td {{
            border: 1px solid {border_color};
            padding: 6px 12px;
        }}

        .markdown-body th {{
            background-color: {code_bg};
            font-weight: 600;
        }}

        .markdown-body hr {{
            border: none;
            border-top: 1px solid {border_color};
            margin: 1em 0;
        }}

        /* Pygments syntax highlighting (dark theme) */
        .codehilite .hll {{ background-color: #49483e }}
        .codehilite .c {{ color: #75715e }} /* Comment */
        .codehilite .k {{ color: #66d9ef }} /* Keyword */
        .codehilite .n {{ color: {text_color} }} /* Name */
        .codehilite .o {{ color: #f92672 }} /* Operator */
        .codehilite .p {{ color: {text_color} }} /* Punctuation */
        .codehilite .cm {{ color: #75715e }} /* Comment.Multiline */
        .codehilite .cp {{ color: #75715e }} /* Comment.Preproc */
        .codehilite .c1 {{ color: #75715e }} /* Comment.Single */
        .codehilite .cs {{ color: #75715e }} /* Comment.Special */
        .codehilite .gd {{ color: #f92672 }} /* Generic.Deleted */
        .codehilite .gi {{ color: #a6e22e }} /* Generic.Inserted */
        .codehilite .kc {{ color: #66d9ef }} /* Keyword.Constant */
        .codehilite .kd {{ color: #66d9ef }} /* Keyword.Declaration */
        .codehilite .kn {{ color: #f92672 }} /* Keyword.Namespace */
        .codehilite .kp {{ color: #66d9ef }} /* Keyword.Pseudo */
        .codehilite .kr {{ color: #66d9ef }} /* Keyword.Reserved */
        .codehilite .kt {{ color: #66d9ef }} /* Keyword.Type */
        .codehilite .ld {{ color: #e6db74 }} /* Literal.Date */
        .codehilite .m {{ color: #ae81ff }} /* Literal.Number */
        .codehilite .s {{ color: #e6db74 }} /* Literal.String */
        .codehilite .na {{ color: #a6e22e }} /* Name.Attribute */
        .codehilite .nb {{ color: #f8f8f2 }} /* Name.Builtin */
        .codehilite .nc {{ color: #a6e22e }} /* Name.Class */
        .codehilite .nd {{ color: #a6e22e }} /* Name.Decorator */
        .codehilite .nf {{ color: #a6e22e }} /* Name.Function */
        .codehilite .nl {{ color: #f8f8f2 }} /* Name.Label */
        .codehilite .nn {{ color: #f8f8f2 }} /* Name.Namespace */
        .codehilite .nt {{ color: #f92672 }} /* Name.Tag */
        .codehilite .nv {{ color: #f8f8f2 }} /* Name.Variable */
        .codehilite .ow {{ color: #f92672 }} /* Operator.Word */
        .codehilite .w {{ color: #f8f8f2 }} /* Text.Whitespace */
        .codehilite .mb {{ color: #ae81ff }} /* Literal.Number.Bin */
        .codehilite .mf {{ color: #ae81ff }} /* Literal.Number.Float */
        .codehilite .mh {{ color: #ae81ff }} /* Literal.Number.Hex */
        .codehilite .mi {{ color: #ae81ff }} /* Literal.Number.Integer */
        .codehilite .mo {{ color: #ae81ff }} /* Literal.Number.Oct */
        .codehilite .sa {{ color: #e6db74 }} /* Literal.String.Affix */
        .codehilite .sb {{ color: #e6db74 }} /* Literal.String.Backtick */
        .codehilite .sc {{ color: #e6db74 }} /* Literal.String.Char */
        .codehilite .dl {{ color: #e6db74 }} /* Literal.String.Delimiter */
        .codehilite .sd {{ color: #e6db74 }} /* Literal.String.Doc */
        .codehilite .s2 {{ color: #e6db74 }} /* Literal.String.Double */
        .codehilite .se {{ color: #ae81ff }} /* Literal.String.Escape */
        .codehilite .sh {{ color: #e6db74 }} /* Literal.String.Heredoc */
        .codehilite .si {{ color: #e6db74 }} /* Literal.String.Interpol */
        .codehilite .sx {{ color: #e6db74 }} /* Literal.String.Other */
        .codehilite .sr {{ color: #e6db74 }} /* Literal.String.Regex */
        .codehilite .s1 {{ color: #e6db74 }} /* Literal.String.Single */
        .codehilite .ss {{ color: #e6db74 }} /* Literal.String.Symbol */
    """

