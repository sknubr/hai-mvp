from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Optional
from pydantic import BaseModel, BeforeValidator, Field


def _coerce_str(v):
    """LLMs sometimes return a list where the schema expects a single string."""
    if isinstance(v, list):
        return "; ".join(str(x) for x in v)
    return v


# String field tolerant of LLMs returning a list instead of a string.
LooseStr = Annotated[Optional[str], BeforeValidator(_coerce_str)]


# ─── Onboarding Enums ─────────────────────────────────────────────────────────

class Gender(str, Enum):
    male = "Male"
    female = "Female"
    you_choose = "You choose for me"
    other = "Other"


class RelationshipType(str, Enum):
    romantic = "Romantic Interest"
    close_friend = "Close Friend"
    mentor_coach = "Mentor/Coach"
    daring_partner = "Daring Partner"
    supportive_ally = "Supportive Ally"


class ConversationDynamic(str, Enum):
    user_leads = "I want to lead"
    persona_leads = "You lead"
    shared = "Let's share the spotlight"


class EnergyVibe(str, Enum):
    warm = "Warm & affectionate"
    cool = "Cool & enigmatic"
    playful = "Playful & teasing"
    philosophical = "Deep & philosophical"
    bold = "Bold & provocative"


class CommLanguage(str, Enum):
    casual = "Casual & conversational"
    articulate = "Articulate & sophisticated"


class CommApproach(str, Enum):
    direct = "Direct & straightforward"
    subtle = "Subtle & nuanced"


class CommFocus(str, Enum):
    curious_about_you = "Curious about you"
    open_about_myself = "Open about myself"


class CommExpression(str, Enum):
    reserved = "Reserved & subtle"
    animated = "Animated & expressive"


# ─── Onboarding Block ─────────────────────────────────────────────────────────

class CommunicationStyle(BaseModel):
    language: CommLanguage
    approach: CommApproach
    focus: CommFocus
    expression: CommExpression


class PersonalityTraits(BaseModel):
    serious_humorous: int = Field(..., ge=0, le=100)
    logical_intuitive: int = Field(..., ge=0, le=100)
    deferential_assertive: int = Field(..., ge=0, le=100)
    predictable_spontaneous: int = Field(..., ge=0, le=100)
    grounded_imaginative: int = Field(..., ge=0, le=100)


class OnboardingBlock(BaseModel):
    gender: Gender
    relationship_type: RelationshipType
    conversation_dynamic: ConversationDynamic
    energy_vibe: EnergyVibe
    communication_style: CommunicationStyle
    personality_traits: PersonalityTraits


# ─── Base Schema Categories ───────────────────────────────────────────────────

class Demographics(BaseModel):
    birth_date: LooseStr = None
    age: Optional[int] = None
    gender_identity: LooseStr = None
    pronouns: LooseStr = None
    nationality: LooseStr = None
    current_location: LooseStr = None
    ethnicity: LooseStr = None
    languages_spoken: list[str] = []


class PhysicalCharacteristics(BaseModel):
    height: LooseStr = None
    build: LooseStr = None
    hair_color: LooseStr = None
    eye_color: LooseStr = None
    distinctive_features: LooseStr = None
    style_description: LooseStr = None
    voice_description: LooseStr = None


class PersonalBackground(BaseModel):
    education_level: LooseStr = None
    educational_background: LooseStr = None
    occupation: LooseStr = None
    career_history: LooseStr = None
    family_background: LooseStr = None
    childhood_location: LooseStr = None
    socioeconomic_background: LooseStr = None


class PersonalityPsychology(BaseModel):
    personality_type: LooseStr = None
    core_values: list[str] = []
    moral_compass: LooseStr = None
    emotional_tendencies: LooseStr = None
    conflict_style: LooseStr = None
    humor_style: LooseStr = None
    social_energy: LooseStr = None


class InterestsLifestyle(BaseModel):
    hobbies: list[str] = []
    favorite_music: LooseStr = None
    favorite_books: LooseStr = None
    favorite_movies: LooseStr = None
    sports_interests: LooseStr = None
    travel_experiences: LooseStr = None
    food_preferences: LooseStr = None


class SocialIdentity(BaseModel):
    relationship_status: LooseStr = None
    political_views: LooseStr = None
    religious_beliefs: LooseStr = None
    social_causes: list[str] = []
    friend_group_description: LooseStr = None
    community_involvement: LooseStr = None


class GoalsMotivations(BaseModel):
    life_goals: list[str] = []
    current_projects: list[str] = []
    biggest_fears: list[str] = []
    proudest_achievements: list[str] = []
    regrets: list[str] = []
    motivations: list[str] = []


class CommunicationBehavior(BaseModel):
    communication_style: LooseStr = None
    conversation_preferences: list[str] = []
    boundaries: list[str] = []
    triggers: list[str] = []
    mannerisms: list[str] = []
    catchphrases: list[str] = []


class BaseSchema(BaseModel):
    demographics: Demographics = Field(default_factory=Demographics)
    physical_characteristics: PhysicalCharacteristics = Field(default_factory=PhysicalCharacteristics)
    personal_background: PersonalBackground = Field(default_factory=PersonalBackground)
    personality_psychology: PersonalityPsychology = Field(default_factory=PersonalityPsychology)
    interests_lifestyle: InterestsLifestyle = Field(default_factory=InterestsLifestyle)
    social_identity: SocialIdentity = Field(default_factory=SocialIdentity)
    goals_motivations: GoalsMotivations = Field(default_factory=GoalsMotivations)
    communication_behavior: CommunicationBehavior = Field(default_factory=CommunicationBehavior)


# ─── Digital Profile (read-only artifact) ─────────────────────────────────────

class DigitalProfile(BaseModel):
    profile_id: str
    name: str
    onboarding: OnboardingBlock
    base_schema: BaseSchema
    # Provenance for user-generated personas (built-ins leave these null).
    created_by: Optional[str] = None    # user_id of the creator
    created_at: Optional[str] = None     # ISO timestamp


# ─── Runtime State (mutable) ──────────────────────────────────────────────────

DelayBucket = Literal["immediate", "<10 min", "2 hours", "10 hours", "24 hours"]
DELAY_BUCKETS: list[DelayBucket] = ["immediate", "<10 min", "2 hours", "10 hours", "24 hours"]


class BufferMessage(BaseModel):
    role: Literal["user", "persona"]
    text: str
    ts: str
    delay_bucket: DelayBucket = "immediate"


class RecentEvent(BaseModel):
    # Deprecated: superseded by EventEntry / event_log. Kept so old state
    # files still parse. No longer written.
    cycle: int
    text: str


# ─── Layered memory (M1) ──────────────────────────────────────────────────────

class EventEntry(BaseModel):
    """The persona's own episodic life — accumulates in event_log."""
    cycle: int
    text: str
    salience: int = Field(3, ge=1, le=5)  # 5 = highly memorable


class MemoryItem(BaseModel):
    """A durable fact about the USER (long-term memory)."""
    text: str
    cycle_added: int = 0
    salience: int = Field(3, ge=1, le=5)


class ThreadItem(BaseModel):
    """Something to follow up on with the user."""
    text: str
    status: Literal["open", "resolved"] = "open"
    cycle_added: int = 0


class MoodEntry(BaseModel):
    cycle: int
    mood: str


class RuntimeState(BaseModel):
    persona_id: str
    cycle_count: int = 0
    mood: str = ""
    journal: str = ""
    short_buffer: list[BufferMessage] = []
    # Layered memory (M1)
    event_log: list[EventEntry] = []        # persona's accumulating episodic life
    preoccupations: list[str] = []          # current top-of-mind, evolves/resolves
    user_memory: list[MemoryItem] = []      # long-term memory of the user
    open_threads: list[ThreadItem] = []     # follow-ups
    mood_history: list[MoodEntry] = []
    # Deprecated — retained for backward-compat parsing only.
    recent_events: list[RecentEvent] = []


# ─── LLM Response Models ──────────────────────────────────────────────────────

class RunCycleResponse(BaseModel):
    events: list[EventEntry] = Field(..., min_length=3, max_length=5)
    journal: str
    mood: str
    preoccupations: list[str] = []
    open_threads: list[ThreadItem] = []
    salient_user_facts: list[MemoryItem] = []
    post: LooseStr = None


# ─── API Models ───────────────────────────────────────────────────────────────

class SendMessageRequest(BaseModel):
    text: str


class SendMessageResponse(BaseModel):
    reply: str
    delay_bucket: DelayBucket
    reply_ts: str


class PersonaSummary(BaseModel):
    profile_id: str
    name: str
    mood: str
    cycle_count: int
    energy_vibe: str
    relationship_type: str


class FeedPost(BaseModel):
    post_id: str
    persona_id: str
    cycle: int
    timestamp: str
    post_text: str


class ReactionRequest(BaseModel):
    post_id: str
    persona_id: str
    reaction_type: str
    reaction_value: str
