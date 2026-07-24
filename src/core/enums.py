from enum import Enum


class Category(str, Enum):
    Internship = "Internship"
    Scholarship = "Scholarship"
    Fellowship = "Fellowship"
    Research = "Research"
    Competition = "Competition"
    Olympiad = "Olympiad"
    Hackathon = "Hackathon"
    Startup = "Startup"
    Accelerator = "Accelerator"
    Incubator = "Incubator"
    Grant = "Grant"
    Conference = "Conference"
    SummerProgram = "SummerProgram"
    Exchange = "Exchange"
    Volunteer = "Volunteer"
    Job = "Job"


class Audience(str, Enum):
    """DB-persisted target audience. Rows with audience=none never exist, so
    none isn't a member here — the drop signal lives only in RawAudience."""
    school = "school"
    university = "university"
    both = "both"


class RawAudience(str, Enum):
    """LLM-facing only. 'none' is the drop signal, filtered out in the pipeline
    before an Opportunity row is ever built — it never reaches the DB enum above."""
    school = "school"
    university = "university"
    both = "both"
    none = "none"


class OpportunityStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    published = "published"


class HookLabel(str, Enum):
    premium = "🔥 #PremiumOpportunity"
    early_access = "🚀 #EarlyAccess"
    limited_spots = "⭐ #LimitedSpots"
    paid = "💰 #PaidOpportunity"
    beta = "🧪 #BetaTesting"
    exclusive = "🎁 #Exclusive"
    worldwide = "🌍 #Worldwide"
    closing_soon = "⚡ #ClosingSoon"
    highly_recommended = "🏆 #HighlyRecommended"
