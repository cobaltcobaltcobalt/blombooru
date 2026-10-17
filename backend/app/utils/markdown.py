from functools import lru_cache

from wenmode import HTMLRenderer, Wenmode
from wenmode.nodes import Text
from wenmode.presets import github
from wenmode.renderers.html import SOFT_BREAK_SPACE_RE, render_list_item

class TailwindHTMLRenderer(HTMLRenderer):
    def __init__(
        self,
        heading_color: str = "primary",
        soft_breaks: bool = False,
        is_description: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.heading_color = heading_color
        self.soft_breaks = soft_breaks
        self.is_description = is_description

@TailwindHTMLRenderer.register("text")
def _render_text(renderer: TailwindHTMLRenderer, node: Text, ctx) -> str:
    escaped = renderer.escape_html(SOFT_BREAK_SPACE_RE.sub("", node.value))
    if renderer.soft_breaks:
        escaped = escaped.replace("\n", "<br />\n")
    return escaped

@TailwindHTMLRenderer.register("heading")
def _render_heading(renderer: TailwindHTMLRenderer, node, ctx) -> str:
    attrs = {}
    if node.data and isinstance(node.data.get("id"), str):
        attrs["id"] = node.data["id"]

    depth = node.depth
    if depth == 1:
        cls = f"text-lg font-bold text-{renderer.heading_color} mt-4 mb-2 first:mt-0"
    elif depth == 2:
        if renderer.heading_color == "info":
            cls = "text-base font-bold text-info mb-2 first:mt-0"
        else:
            cls = f"text-base font-bold text-{renderer.heading_color} border-b border-border pb-1 mt-4 mb-2 first:mt-0"
    elif depth == 3:
        if renderer.heading_color == "info":
            cls = "text-xs font-bold uppercase tracking-wider text-secondary mt-3 mb-1 first:mt-0"
        else:
            cls = f"text-sm font-bold text-{renderer.heading_color} mt-3 mb-1 first:mt-0"
    else:
        cls = "text-xs font-bold text-secondary mt-2 mb-1 first:mt-0"

    attrs["class"] = cls
    return f"<h{depth}{renderer.render_attrs(attrs)}>{renderer.render_children(node.children, ctx)}</h{depth}>\n"

@TailwindHTMLRenderer.register("paragraph")
def _render_paragraph(renderer: TailwindHTMLRenderer, node, ctx) -> str:
    text_size = "text-xs" if renderer.is_description else "text-sm"
    return f'<p class="mb-3 {text_size} last:mb-0 leading-relaxed">{renderer.render_children(node.children, ctx)}</p>\n'

@TailwindHTMLRenderer.register("list")
def _render_list(renderer: TailwindHTMLRenderer, node, ctx) -> str:
    tag = "ol" if node.ordered else "ul"
    list_type = "list-decimal" if node.ordered else "list-disc"
    text_size = "text-xs" if renderer.is_description else "text-sm"
    attrs = {"class": f"{list_type} pl-5 mb-3 last:mb-0 space-y-1 {text_size}"}
    if node.ordered and node.start not in (None, 1):
        attrs["start"] = node.start

    items = "".join(render_list_item(renderer, child, node.spread, ctx) for child in node.children)
    items = items.replace("<li>", '<li class="leading-normal">')
    return f"<{tag}{renderer.render_attrs(attrs)}>\n{items}</{tag}>\n"

@TailwindHTMLRenderer.register("inlineCode")
def _render_inline_code(renderer: TailwindHTMLRenderer, node, ctx) -> str:
    return f'<code class="bg-surface px-1 py-0.5 font-mono text-xs">{renderer.escape_html(node.value)}</code>'

@TailwindHTMLRenderer.register("code")
def _render_code(renderer: TailwindHTMLRenderer, node, ctx) -> str:
    lang_cls = f" language-{node.lang}" if node.lang else ""
    return (
        f'<pre class="bg-surface p-2 mb-3 last:mb-0 overflow-x-auto text-xs font-mono max-h-60 overflow-y-auto whitespace-pre-wrap break-words">'
        f'<code class="bg-transparent p-0{lang_cls}">{renderer.escape_html(node.value)}</code>'
        f"</pre>\n"
    )

@TailwindHTMLRenderer.register("link")
def _render_link(renderer: TailwindHTMLRenderer, node, ctx) -> str:
    url = renderer.sanitize_url(node.url)
    attrs = {
        "href": url,
        "class": "text-primary hover:text-primary-hover transition-colors",
        "target": "_blank",
        "rel": "noopener noreferrer",
        "referrerPolicy": "no-referrer",
    }
    if node.title:
        attrs["title"] = node.title
    return f"<a{renderer.render_attrs(attrs)}>{renderer.render_children(node.children, ctx)}</a>"

@TailwindHTMLRenderer.register("blockquote")
def _render_blockquote(renderer: TailwindHTMLRenderer, node, ctx) -> str:
    if renderer.is_description:
        return f'<blockquote class="border-l-2 border-primary surface p-2 pl-3 text-secondary mb-3">{renderer.render_children(node.children, ctx)}</blockquote>\n'
    return f'<blockquote class="border-l-2 border-primary pl-3 text-secondary mb-3">{renderer.render_children(node.children, ctx)}</blockquote>\n'

@lru_cache(maxsize=8)
def _get_renderer(heading_color: str, soft_breaks: bool, is_description: bool) -> Wenmode:
    return Wenmode(
        github(),
        renderer=TailwindHTMLRenderer(
            heading_color=heading_color,
            soft_breaks=soft_breaks,
            is_description=is_description,
        ),
    )

def render_markdown(
    text: str,
    heading_color: str = "primary",
    soft_breaks: bool = False,
    is_description: bool = False,
) -> str:
    """Render markdown to HTML with Tailwind CSS classes on all elements."""
    if not text:
        return ""
    return _get_renderer(heading_color, soft_breaks, is_description).render(text)

def render_description_markdown(text: str, heading_color: str = "primary") -> str:
    """Render a media description with soft breaks and description-specific sizing."""
    return render_markdown(
        text, heading_color=heading_color, soft_breaks=True, is_description=True
    )
