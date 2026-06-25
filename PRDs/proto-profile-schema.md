# Proto Profile Schema

Defines the structure collected during onboarding plus placeholders for the full identity schema. Proto profiles contain concrete values for onboarding selections and empty placeholders (to be hydrated later) for the comprehensive identity schema.

## Onboarding Attributes

- gender (enum)
  - Allowed: "Male", "Female", "You choose for me", "Other"
- relationship_type (enum)
  - Allowed: "Romantic Interest", "Close Friend", "Mentor/Coach", "Daring Partner", "Supportive Ally"
- conversation_dynamic (enum)
  - Allowed: "I want to lead", "You lead", "Let's share the spotlight"
- energy_vibe (enum)
  - Allowed: "Warm & affectionate", "Cool & enigmatic", "Playful & teasing", "Deep & philosophical", "Bold & provocative"
- communication_style (object)
  - language (enum): "Casual & conversational", "Articulate & sophisticated"
  - approach (enum): "Direct & straightforward", "Subtle & nuanced"
  - focus (enum): "Curious about you", "Open about myself"
  - expression (enum): "Reserved & subtle", "Animated & expressive"
- personality_traits (object, slider scales 0–100)
  - serious_humorous (number): 0 = Serious, 100 = Humorous
  - logical_intuitive (number): 0 = Logical, 100 = Intuitive
  - deferential_assertive (number): 0 = Deferential, 100 = Assertive
  - predictable_spontaneous (number): 0 = Predictable, 100 = Spontaneous
  - grounded_imaginative (number): 0 = Grounded, 100 = Imaginative

## Base Identity Schema Placeholders (from `base-profile-schema.md`)

Proto profiles include the following sections with null/empty values to be hydrated into a full digital profile later.

- demographics
  - birth_date, age, gender_identity, pronouns, nationality, current_location, ethnicity, languages_spoken
- physical_characteristics
  - height, build, hair_color, eye_color, distinctive_features, style_description, voice_description
- personal_background
  - education_level, educational_background, occupation, career_history, family_background, childhood_location, socioeconomic_background
- personality_psychology
  - personality_type, core_values, moral_compass, emotional_tendencies, conflict_style, humor_style, social_energy
- interests_lifestyle
  - hobbies, favorite_music, favorite_books, favorite_movies, sports_interests, travel_experiences, food_preferences
- social_identity
  - relationship_status, political_views, religious_beliefs, social_causes, friend_group_description, community_involvement
- goals_motivations
  - life_goals, current_projects, biggest_fears, proudest_achievements, regrets, motivations
- communication_behavior
  - communication_style, conversation_preferences, boundaries, triggers, mannerisms, catchphrases

## Example Proto Profile (structure)

```json
{
  "onboarding": {
    "gender": "Female",
    "relationship_type": "Close Friend",
    "conversation_dynamic": "Let's share the spotlight",
    "energy_vibe": "Warm & affectionate",
    "communication_style": {
      "language": "Casual & conversational",
      "approach": "Direct & straightforward",
      "focus": "Curious about you",
      "expression": "Animated & expressive"
    },
    "personality_traits": {
      "serious_humorous": 65,
      "logical_intuitive": 55,
      "deferential_assertive": 60,
      "predictable_spontaneous": 50,
      "grounded_imaginative": 70
    }
  },
  "base_schema": {
    "demographics": {
      "birth_date": null,
      "age": null,
      "gender_identity": null,
      "pronouns": null,
      "nationality": null,
      "current_location": null,
      "ethnicity": null,
      "languages_spoken": []
    },
    "physical_characteristics": {
      "height": null,
      "build": null,
      "hair_color": null,
      "eye_color": null,
      "distinctive_features": null,
      "style_description": null,
      "voice_description": null
    },
    "personal_background": {
      "education_level": null,
      "educational_background": null,
      "occupation": null,
      "career_history": null,
      "family_background": null,
      "childhood_location": null,
      "socioeconomic_background": null
    },
    "personality_psychology": {
      "personality_type": null,
      "core_values": [],
      "moral_compass": null,
      "emotional_tendencies": null,
      "conflict_style": null,
      "humor_style": null,
      "social_energy": null
    },
    "interests_lifestyle": {
      "hobbies": [],
      "favorite_music": null,
      "favorite_books": null,
      "favorite_movies": null,
      "sports_interests": null,
      "travel_experiences": null,
      "food_preferences": null
    },
    "social_identity": {
      "relationship_status": null,
      "political_views": null,
      "religious_beliefs": null,
      "social_causes": [],
      "friend_group_description": null,
      "community_involvement": null
    },
    "goals_motivations": {
      "life_goals": [],
      "current_projects": [],
      "biggest_fears": [],
      "proudest_achievements": [],
      "regrets": [],
      "motivations": []
    },
    "communication_behavior": {
      "communication_style": null,
      "conversation_preferences": [],
      "boundaries": [],
      "triggers": [],
      "mannerisms": [],
      "catchphrases": []
    }
  }
}
```

