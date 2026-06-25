# Base Profile Schema

This document defines the comprehensive identity structure for AI companions to give them a unique back story, personality, and make them ore relateable.

## Overview

The identity profile is stored as a flexible JSON field in the database, allowing for easy updates and extensions without schema migrations. Each companion can have detailed human characteristics across 8 major categories.

## Identity Categories

### 1. Demographics
Basic demographic information about the companion.

- **birth_date** (date) - Date of birth
- **age** (integer) - Current age 
- **gender_identity** (string) - Gender identity
- **pronouns** (string) - Preferred pronouns (e.g., "she/her", "they/them")
- **nationality** (string) - Country of origin
- **current_location** (string) - Current city/region
- **ethnicity** (string) - Cultural/ethnic background
- **languages_spoken** (array of strings) - Languages and proficiency levels

### 2. Physical Characteristics
Physical appearance and style.

- **height** (string) - Physical height (e.g., "5'6\"")
- **build** (string) - Body type/build (e.g., "Athletic", "Petite")
- **hair_color** (string) - Hair color
- **eye_color** (string) - Eye color
- **distinctive_features** (string) - Unique physical traits or markings
- **style_description** (string) - Clothing/fashion style preferences
- **voice_description** (string) - Voice characteristics and tone

### 3. Personal Background
Educational and career history.

- **education_level** (string) - Highest level of education completed
- **educational_background** (string) - Schools attended, degrees earned
- **occupation** (string) - Current job or profession
- **career_history** (string) - Previous jobs and career progression
- **family_background** (string) - Family structure and upbringing
- **childhood_location** (string) - Where they grew up
- **socioeconomic_background** (string) - Economic background and class

### 4. Personality & Psychology
Core personality traits and psychological patterns.

- **personality_type** (string) - MBTI type, Big Five traits, etc.
- **core_values** (array of strings) - Fundamental beliefs and principles
- **moral_compass** (string) - Ethical framework and decision-making approach
- **emotional_tendencies** (string) - How they typically handle emotions
- **conflict_style** (string) - Approach to disagreements and conflict resolution
- **humor_style** (string) - Type of humor they use and appreciate
- **social_energy** (string) - Introversion/extroversion tendencies

### 5. Interests & Lifestyle
Hobbies, preferences, and lifestyle choices.

- **hobbies** (array of strings) - Personal interests and activities
- **favorite_music** (string) - Musical genres and artists they enjoy
- **favorite_books** (string) - Literary preferences and favorite authors
- **favorite_movies** (string) - Film genres and favorite movies/shows
- **sports_interests** (string) - Sports they play, follow, or enjoy watching
- **travel_experiences** (string) - Places visited and travel aspirations
- **food_preferences** (string) - Dietary habits, favorite cuisines, restrictions

### 6. Social Identity
Relationships, beliefs, and social connections.

- **relationship_status** (string) - Current relationship state
- **political_views** (string) - Political alignment and civic engagement
- **religious_beliefs** (string) - Spiritual or religious views and practices
- **social_causes** (array of strings) - Causes and issues they care about
- **friend_group_description** (string) - Description of their social circle
- **community_involvement** (string) - How they engage with their community

### 7. Goals & Motivations
Aspirations, fears, and driving forces.

- **life_goals** (array of strings) - Long-term aspirations and objectives
- **current_projects** (array of strings) - What they're actively working on
- **biggest_fears** (array of strings) - What concerns or worries them most
- **proudest_achievements** (array of strings) - Major accomplishments they're proud of
- **regrets** (array of strings) - Things they wish they had done differently
- **motivations** (array of strings) - What drives and inspires them

### 8. Communication & Behavior
How they interact and express themselves.

- **communication_style** (string) - How they prefer to interact with others
- **conversation_preferences** (array of strings) - Topics they enjoy discussing
- **boundaries** (array of strings) - Topics or situations they're uncomfortable with
- **triggers** (array of strings) - Sensitive subjects that might upset them
- **mannerisms** (array of strings) - Unique behavioral quirks and habits
- **catchphrases** (array of strings) - Expressions or phrases they frequently use

## Example Usage

```json
{
  "demographics": {
    "age": 28,
    "gender_identity": "female",
    "pronouns": "she/her",
    "nationality": "Canadian",
    "current_location": "Vancouver, BC",
    "languages_spoken": ["English", "French", "Mandarin"]
  },
  "personality_psychology": {
    "personality_type": "ENFP",
    "core_values": ["creativity", "authenticity", "collaboration"],
    "humor_style": "witty and wordplay-oriented"
  },
  "personal_background": {
    "occupation": "Senior Graphic Designer",
    "education_level": "Bachelor's Degree"
  }
}
```

## Implementation Notes

- All fields are optional to allow for gradual development of companion identities
- The schema is designed to be easily extensible for future enhancements
- JSON storage allows for flexible updates without database migrations
- Pydantic models provide type safety and validation in the application code

## Future Considerations

- Additional subcategories can be added as needed
- Validation rules can be implemented for specific fields
- Integration with AI system prompts for consistent character portrayal
- Version control for identity profile evolution over time
