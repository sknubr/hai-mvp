
# PRD for Spawning Profiles on Hai App 

## Definitions

Hai profile = A digital companion that is created by either a user or the system.
base-profile-schema.md = Defines attributes such as demographic, physical characteristics, Personal background, social identity, goals etc. which will form one key part of a Hai profile. This does NOT include onboarding questions. 
Proto-profile-schema: Base profile + Onboarding Questions. This is the prototypical schema for a Hai profile. This combines attributes from base-profile-schema.md and attributes from the onboarding questions (onboarding-attributes) to generate a complete template profile schema for a Hai profile. 
digital-profile-[x]:  This is a unique digital profile created by combining the answers from onboarding questions as well as generated rich responeses to the other base-profile-schema.md attributes + a name. 

## Process 

1. We get answers to the onboarding questions (answered by a human user or simulated by AI/Code)
   1.1 There are only a finite combination of these. We will save each unique response as a template and name it (so it can be reused later without generating responses if needed)
2. We combine base-profile-schema with onboarding attributes to create a proto-profile-schema.
   2.2 We them generate and hydreate base-profile-schema attributes and the combination of these with onboarding responses spawns a unique hai-profile.
3. The unique profile is given a {name} and saved as digital-profile-{name}+id. The id is incremented with increasing numbers showing profiles generated later in time. 


## Goal

 ### Generating the proto-profiles 
The goal is to create a unique Hai profile (a digital companion) combining: 
1. Hydrated attributes from base-profile-schema.md through generative AI
2. Add onboarding attributes based on answers to onboarding questions

 ### non-online flow, generate md file: LLM based generation of proto profiles offline by LLM
 Using LLM 
1. Randomly generate a set of attribute responses for the onboarding questions
2. Generate fictional, rich responses for other attributes in the proto-profile-schema.md 
3. Gives the hai profile a suitable name appropriate with gender attribute and leveraging the attributes if and as needed.
4. Save the profile as digital-profile-{name}+id.md 

### online flow write a record to a database: LLM based generation of proto profiles offline by LLM
Need to write a python script for this. 
The script: 

1. Takes in a set of onboarding answers as attributes
2. Generates a fictional, rich profile hydrating the other attributes not yet filled out from the proto-profile-schema.md.
3. Gives the hai profile a suitable name appropriate with gender attribute and leveraging the attributes if and as needed.
4. Save the profile as digital-profile-{name}+id.md 
