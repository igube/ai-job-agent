"""Offline, rule-based CV extraction. No external API calls.

Splits raw CV text into a contact block (parsed via regex) and named
sections (kept as raw text — structuring individual entries is left to
the AI stage, see docs/architecture.md).
"""

import re

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:\+?\d[\d\s-]{7,}\d)")
GITHUB_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[\w-]+", re.IGNORECASE)
LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w-]+", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s,;]+", re.IGNORECASE)
LOCATION_RE = re.compile(r"^[A-ZŁŚŻŹĆŃÓĄĘ][\wąćęłńóśźż]+(?:\s*[/,]\s*[A-ZŁŚŻŹĆŃÓĄĘ][\wąćęłńóśźż]+)*$")

SECTION_KEYWORDS: dict[str, list[str]] = {
    "summary": ["PODSUMOWANIE", "PROFIL", "SUMMARY", "O MNIE", "ABOUT"],
    "experience": ["DOSWIADCZENIE", "DOŚWIADCZENIE", "EXPERIENCE", "STAZ", "STAŻ"],
    "education": ["WYKSZTALCENIE", "WYKSZTAŁCENIE", "EDUCATION"],
    "skills": ["UMIEJETNOSCI", "UMIEJĘTNOŚCI", "SKILLS", "KOMPETENCJE"],
    "projects": ["PROJEKTY", "PROJECTS"],
    "languages": ["JEZYKI", "JĘZYKI", "LANGUAGES"],
    "certificates": ["CERTYFIKATY", "CERTIFICATES", "KURSY", "COURSES"],
}

SKILL_SPLIT_RE = re.compile(r"[\n,;•|]+")


def _normalize_header(line: str) -> str:
    return line.strip().strip(":").upper()


def _match_section(line: str) -> str | None:
    norm = _normalize_header(line)
    if not norm or len(norm) > 60:
        return None
    for canonical, keywords in SECTION_KEYWORDS.items():
        for kw in keywords:
            if norm.startswith(kw):
                return canonical
    return None


def split_sections(text: str) -> dict[str, str]:
    """Split CV text into named sections based on heading keywords.

    Text before the first recognized heading is returned under "header"
    (name, contact info, optional tagline).
    """
    lines = text.splitlines()
    boundaries: list[tuple[int, str]] = [(0, "header")]

    for i, line in enumerate(lines):
        section = _match_section(line)
        if section is not None:
            boundaries.append((i, section))

    sections: dict[str, list[str]] = {}
    for idx, (start, name) in enumerate(boundaries):
        end = boundaries[idx + 1][0] if idx + 1 < len(boundaries) else len(lines)
        content_start = start + 1 if name != "header" else start
        chunk = "\n".join(lines[content_start:end]).strip()
        if not chunk:
            continue
        sections.setdefault(name, [])
        sections[name].append(chunk)

    return {name: "\n".join(parts).strip() for name, parts in sections.items()}


def extract_contact(header_text: str) -> dict:
    email = EMAIL_RE.search(header_text)
    phone = PHONE_RE.search(header_text)
    github = GITHUB_RE.search(header_text)
    linkedin = LINKEDIN_RE.search(header_text)

    urls = URL_RE.findall(header_text)
    website = next(
        (u for u in urls if "github.com" not in u.lower() and "linkedin.com" not in u.lower()),
        None,
    )

    lines = [l.strip() for l in header_text.splitlines() if l.strip()]
    name = lines[0] if lines and len(lines[0]) < 60 and not EMAIL_RE.search(lines[0]) else None

    location = None
    for line in lines[1:6]:
        if EMAIL_RE.search(line) or PHONE_RE.search(line):
            continue
        if GITHUB_RE.search(line) or LINKEDIN_RE.search(line) or URL_RE.search(line):
            continue
        if LOCATION_RE.match(line.strip()):
            location = line.strip()
            break

    return {
        "name": name,
        "email": email.group(0) if email else None,
        "phone": phone.group(0).strip() if phone else None,
        "location": location,
        "linkedin": linkedin.group(0) if linkedin else None,
        "github": github.group(0) if github else None,
        "website": website,
    }


def extract_header_summary(header_text: str) -> str:
    """Many CVs put a profile blurb right under the contact block, with no
    heading of its own. It usually states what the candidate is actually
    looking for ("szukam stażu w obszarze AI"), which matters a lot for
    matching -- so it must not be discarded along with the contact lines.

    Heuristic: keep header lines that read like prose (long, containing
    spaces) rather than contact details or a bare name.
    """
    prose: list[str] = []
    for line in header_text.splitlines():
        line = line.strip()
        if len(line) < 40 or " " not in line:
            continue
        if EMAIL_RE.search(line) or PHONE_RE.search(line) or URL_RE.search(line):
            continue
        prose.append(line)
    return " ".join(prose).strip()


def extract_skills(skills_text: str) -> list[str]:
    if not skills_text:
        return []
    raw_items = SKILL_SPLIT_RE.split(skills_text)
    seen: dict[str, None] = {}
    for item in raw_items:
        skill = item.strip(" \t-•*").strip()
        if skill and skill not in seen:
            seen[skill] = None
    return list(seen.keys())


def parse_cv_local(text: str) -> dict:
    """Parse raw CV text offline into contact fields + raw sections.

    Entries inside experience/education/projects are NOT individually
    structured here (dates, company, position) — that requires semantic
    understanding an AI stage will add later. This stage guarantees
    accurate contact extraction and a clean, section-split JSON.
    """
    sections = split_sections(text)
    header_text = sections.pop("header", "")

    contact = extract_contact(header_text)
    skills = extract_skills(sections.get("skills", ""))
    summary = sections.pop("summary", "") or extract_header_summary(header_text)

    return {
        "contact": contact,
        "summary": summary or None,
        "sections": sections,
        "skills": skills,
    }
