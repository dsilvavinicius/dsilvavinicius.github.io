#!/usr/bin/env python3
"""Generate index.html from the YAML files in data/.

    python build.py            regenerate index.html
    python build.py --serve    regenerate, then serve on http://localhost:4321

index.html is committed and uses relative paths, so you can also just open it
straight from disk to check a change before committing. Needs PyYAML
(pip install pyyaml).
"""

import argparse
import html
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))

FONTS = ("https://fonts.googleapis.com/css2"
         "?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,700"
         "&family=Archivo:wght@400;500;600"
         "&family=JetBrains+Mono:wght@400;500&display=swap")

LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def load(name):
    with open(os.path.join(ROOT, "data", name), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def esc(text):
    return html.escape(str(text), quote=True)


def inline_links(text):
    """[label](url) -> <a href="url">label</a>, everything else escaped."""
    out, pos = [], 0
    for m in LINK_RE.finditer(text):
        out.append(esc(text[pos:m.start()]))
        out.append(f'<a href="{esc(m.group(2))}">{esc(m.group(1))}</a>')
        pos = m.end()
    out.append(esc(text[pos:]))
    return "".join(out)


def authors_html(text):
    """[Name] -> bold. The brackets mark your own name in the author list."""
    return esc(text).replace("[", "<strong>").replace("]", "</strong>")


PLAY_ICON = ('<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"'
             ' aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>')


def figure_html(pub):
    title = esc(pub["title"])
    if pub.get("youtube"):
        # A thumbnail linking out, not an <iframe>: embeds refuse to initialise
        # from a file:// origin, so an iframe breaks the open-it-from-disk check.
        vid = esc(pub["youtube"])
        poster = (esc(pub["poster"]) if pub.get("poster")
                  else f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg")
        return (f'<a class="pub__fig pub__fig--video"'
                f' href="https://www.youtube.com/watch?v={vid}">'
                f'<img src="{poster}" alt="Watch the video for {title} on YouTube"'
                f' loading="lazy">'
                f'<span class="pub__play">{PLAY_ICON}</span></a>')
    if pub.get("video"):
        src = esc(pub["video"])
        # The poster keeps a frame on screen when autoplay is blocked or deferred.
        poster = f' poster="{esc(pub["poster"])}"' if pub.get("poster") else ""
        return (f'<div class="pub__fig">'
                f'<video src="{src}"{poster} autoplay muted loop playsinline preload="metadata"'
                f' aria-label="Animated figure for {title}"></video></div>')
    if pub.get("image"):
        src = esc(pub["image"])
        return (f'<a class="pub__fig" href="{src}">'
                f'<img src="{src}" alt="Figure from {title}" loading="lazy"></a>')
    return ""


def publication_html(pub, show_year):
    fig = figure_html(pub)
    cls = "pub" if fig else "pub pub--nofig"
    links = ""
    if pub.get("links"):
        parts = [f'<a href="{esc(l["url"])}">{esc(l["text"])}</a>' for l in pub["links"]]
        links = ('\n        <p class="pub__links">'
                 + '<span aria-hidden="true"> · </span>'.join(parts) + '</p>')
    return f"""      <article class="{cls}">
        <p class="pub__year">{esc(pub["year"]) if show_year else ""}</p>
        <div class="pub__body">
          <p class="pub__venue">{esc(pub["venue"])}</p>
          <h3 class="pub__title"><a href="{esc(pub["url"])}">{esc(pub["title"])}</a></h3>
          <p class="pub__authors">{authors_html(pub["authors"])}</p>{links}
        </div>
        {fig}
      </article>"""


def project_html(project):
    figs = "\n".join(
        f'          <a href="{esc(img)}"><img src="{esc(img)}"'
        f' alt="Screenshot from {esc(project["name"])}" loading="lazy"></a>'
        for img in project.get("images", []))
    count = len(project.get("images", []))
    return f"""      <article class="project">
        <div class="project__figs project__figs--{count}">
{figs}
        </div>
        <div class="project__body">
          <h3 class="project__title"><a href="{esc(project["url"])}">{esc(project["name"])}</a></h3>
          <p class="project__text">{esc(project["description"])}</p>
        </div>
      </article>"""


PORTRAIT_PX = 600          # 2.5x the 232px it renders at, so it stays sharp on retina
PORTRAIT_DERIVED = "figs/photo.web.jpg"


def web_portrait(source):
    """Shrink the portrait for the web so a multi-megabyte original isn't served.

    Regenerated whenever the source is newer, so dropping in a new photo.png and
    re-running this script is enough. Without Pillow the original is used as-is.
    """
    src = os.path.join(ROOT, source)
    if not os.path.exists(src):
        print(f"  warning: {source} is missing — using it as named", file=sys.stderr)
        return source
    try:
        from PIL import Image
    except ImportError:
        print("  note: Pillow not installed, serving the portrait at full size",
              file=sys.stderr)
        return source

    out = os.path.join(ROOT, PORTRAIT_DERIVED)
    if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(src):
        return PORTRAIT_DERIVED

    image = Image.open(src).convert("RGB")
    side = min(image.size)                       # square crop, centred
    left, top = (image.width - side) // 2, (image.height - side) // 2
    image = image.crop((left, top, left + side, top + side))
    image = image.resize((PORTRAIT_PX, PORTRAIT_PX), Image.LANCZOS)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    image.save(out, "JPEG", quality=88, optimize=True, progressive=True)
    print(f"  portrait: {source} -> {PORTRAIT_DERIVED} "
          f"({os.path.getsize(out) // 1024} KB)")
    return PORTRAIT_DERIVED


def check_assets(publications, projects):
    """Warn about figures named in the YAML that are not on disk."""
    referenced = []
    for pub in publications:
        referenced += [pub[k] for k in ("image", "video") if pub.get(k)]
    for project in projects:
        referenced += project.get("images", [])
    missing = [p for p in referenced
               if not p.startswith(("http://", "https://"))
               and not os.path.exists(os.path.join(ROOT, p))]
    for path in missing:
        print(f"  warning: {path} is referenced but not on disk", file=sys.stderr)
    return missing


def render():
    site = load("site.yml")
    publications = load("publications.yml")
    projects = load("projects.yml")

    missing = check_assets(publications, projects)
    portrait = esc(web_portrait(site["portrait"]))

    rows, last_year = [], None
    for pub in publications:
        rows.append(publication_html(pub, pub["year"] != last_year))
        last_year = pub["year"]

    bio = "\n        ".join(f"<p>{inline_links(p)}</p>" for p in site["bio"])
    chips = "\n        ".join(
        f'<li><a class="chip" href="{esc(l["url"])}">{esc(l["text"])}</a></li>'
        for l in site["links"])
    affiliations = "".join(f"<li>{esc(a)}</li>" for a in site["affiliations"])
    footer_links = "".join(
        f'<li><a href="{esc(l["url"])}">{esc(l["text"])}</a></li>' for l in site["links"])
    description = esc(" ".join(site["description"].split()))
    mail = esc(site["email"])

    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(site["title"])} — {esc(site["tagline"])}</title>
  <meta name="description" content="{description}">
  <meta name="author" content="{esc(site["title"])}">

  <meta property="og:type" content="profile">
  <meta property="og:title" content="{esc(site["title"])}">
  <meta property="og:description" content="{description}">
  <meta property="og:url" content="{esc(site["url"])}">
  <meta property="og:image" content="{esc(site["url"])}/{portrait}">
  <meta name="twitter:card" content="summary">

  <link rel="canonical" href="{esc(site["url"])}">
  <link rel="icon" href="{portrait}">

  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="{FONTS}">

  <link rel="stylesheet" href="assets/css/style.css">
</head>
<body>

<!-- Generated by build.py from data/*.yml — edit those, not this file. -->

<a class="skip-link" href="#publications">Skip to publications</a>

<div class="page">

  <header class="masthead">
    <div class="masthead__text">
      <p class="eyebrow">{esc(site["eyebrow"])}</p>
      <h1 class="masthead__name">{esc(site["title"])}</h1>
      <div class="bio">
        {bio}
      </div>
      <ul class="chips">
        {chips}
        <li><a class="chip chip--primary" href="mailto:{mail}">{mail}</a></li>
      </ul>
    </div>
    <div class="masthead__portrait">
      <img class="portrait" src="{portrait}" alt="Portrait of {esc(site["title"])}" width="232" height="232">
    </div>
  </header>

  <ul class="affiliations">{affiliations}</ul>

  <section id="publications" class="section">
    <div class="section__head">
      <h2>Publications</h2>
      <p class="section__note">{len(publications)} entries · journals, conferences, books and preprints</p>
    </div>

    <div class="pubs">
{chr(10).join(rows)}
    </div>
  </section>

  <section id="projects" class="section">
    <div class="section__head">
      <h2>Projects</h2>
    </div>

{chr(10).join(project_html(p) for p in projects)}
  </section>

  <footer class="footer">
    <p class="footer__mail"><a href="mailto:{mail}">{mail}</a></p>
    <ul class="footer__links">{footer_links}</ul>
  </footer>

</div>

</body>
</html>
"""

    out = os.path.join(ROOT, "index.html")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(page)

    figures = sum(1 for p in publications if p.get("image") or p.get("video") or p.get("youtube"))
    print(f"wrote index.html — {len(publications)} publications "
          f"({figures} with a figure), {len(projects)} projects")
    if missing:
        print(f"  {len(missing)} missing figure(s) — see warnings above")
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--serve", action="store_true",
                        help="serve the site on http://localhost:4321 after building")
    parser.add_argument("--port", type=int, default=4321)
    args = parser.parse_args()

    out = render()

    if args.serve:
        import functools
        import http.server
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
        print(f"serving http://localhost:{args.port} — Ctrl+C to stop")
        http.server.ThreadingHTTPServer(("", args.port), handler).serve_forever()
    else:
        print(f"open {out} in a browser to check it")


if __name__ == "__main__":
    main()
