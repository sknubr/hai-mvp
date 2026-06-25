from __future__ import annotations

from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, Field


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
    birth_date: Optional[str] = None
    age: Optional[int] = None
    gender_identity: Optional[str] = None
    pronouns: Optional[str] = None
    nationality: Optional[str] = None
    current_location: Optional[str] = None
    ethnicity: Optional[str] = None
    languages_spoken: list[str] = []


class PhysicalCharacteristics(BaseModel):
    height: Optional[str] = None
    build: Optional[str] = None
    hair_color: Optional[str] = None
    eye_color: Optional[str] = None
    distinctive_features: Optional[str] = None
    style_description: Optional[str] = None
    voice_description: Optional[str] = None


class PersonalBackground(BaseModel):
    education_level: Optional[str] = None
    educational_background: Optional[str] = None
    occupation: Optional[str] = None
    career_history: Optional[str] = None
    family_background: Optional[str] = None
    childhood_location: Optional[str] = None
    socioeconomic_background: Optional[str] = None


class PersonalityPsychology(BaseModel):
    personality_type: Optional[str] = None
    core_values: list[str] = []
    moral_compass: Optional[str] = None
    emotional_tendencies: Optional[str] = None
    conflict_style: Optional[str] = None
    humor_style: Optional[str] = None
    social_energy: Optional[str] = None


class InterestsLifestyle(BaseModel):
    hobbies: list[str] = []
    favorite_music: Optional[str] = None
    favorite_books: Optional[str] = None
    favorite_movies: Optional[str] = None
    sports_interests: Optional[str] = None
    travel_experiences: Optional[str] = None
    food_preferences: Optional[str] = None


class SocialIdentity(BaseModel):
    relationship_status: Optional[str] = None
    political_views: Optional[str] = None
    religious_beliefs: Optional[str] = None
    social_causes: list[str] = []
    friend_group_description: Optional[str] = None
    community_involvement: Optional[str] = None


class GoalsMotivations(BaseModel):
    life_goals: list[str] = []
    current_projects: list[str] = []
    biggest_fears: list[str] = []
    proudest_achievements: list[str] = []
    regrets: list[str] = []
    motivations: list[str] = []


class CommunicationBehavior(BaseModel):
    communication_style: Optional[str] = None
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


# ─── Runtime State (mutable) ──────────────────────────────────────────────────

DelayBucket = Literal["immediate", "<10 min", "2 hours", "10 hours", "24 hours"]
DELAY_BUCKETS: list[DelayBucket] = ["immediate", "<10 min", "2 hours", "10 hours", "24 hours"]


class BufferMessage(BaseModel):
    role: Literal["user", "persona"]
    text: str
    ts: str
    delay_bucket: DelayBucket = "immediate"


class RecentEvent(BaseModel):
    cycle: int
    text: str


class RuntimeState(BaseModel):
    persona_id: str
    cycle_count: int = 0
    mood: str = ""
    journal: str = ""
    recent_events: list[RecentEvent] = []
    short_buffer: list[BufferMessage] = []


# ─── LLM Response Models ──────────────────────────────────────────────────────

class RunCycleResponse(BaseModel):
    events: list[str] = Field(..., min_length=3, max_length=5)
    journal: str
    mood: str
    post: Optional[str] = None


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
