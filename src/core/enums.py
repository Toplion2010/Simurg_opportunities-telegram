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
