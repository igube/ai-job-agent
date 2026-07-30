from pydantic import BaseModel


class Contact(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin: str | None = None
    github: str | None = None
    website: str | None = None


class CVProfileRaw(BaseModel):
    """Etap 1 (offline) output: contact fields + raw text per CV section."""

    source_file: str
    summary: str | None = None
    contact: Contact
    sections: dict[str, str] = {}
    skills: list[str] = []


# --- Etap 2 (AI) target schema — not produced yet, kept here so the
# offline output above has a documented upgrade path. ---


class Experience(BaseModel):
    company: str | None = None
    position: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    location: str | None = None
    description: str | None = None


class Project(BaseModel):
    name: str | None = None
    description: str | None = None
    tech_stack: list[str] = []
    url: str | None = None


class Education(BaseModel):
    institution: str | None = None
    degree: str | None = None
    field: str | None = None
    start_date: str | None = None
    end_date: str | None = None


class CVProfileStructured(BaseModel):
    contact: Contact
    # Candidate's own profile blurb -- typically states what they are looking
    # for, which is exactly what skill lists cannot express.
    summary: str | None = None
    experience: list[Experience] = []
    skills: list[str] = []
    projects: list[Project] = []
    education: list[Education] = []
    languages: list[str] = []


# --- Etap 3 (job scraping) ---


class SalaryRange(BaseModel):
    contract_type: str
    unit: str
    amount_from: float | None = None
    amount_to: float | None = None
    currency: str


class JobPosting(BaseModel):
    source: str
    external_id: str
    title: str
    company: str
    city: str | None = None
    workplace_type: str | None = None
    experience_level: str | None = None
    category: str | None = None
    skills: list[str] = []
    salary: list[SalaryRange] = []
    url: str
    apply_url: str | None = None
    published_at: str | None = None
    description: str | None = None
