"use client";

import { useBusiness } from "@/lib/business";

/** Words that change with the business type, mirroring each pack's vocab in WAM core. */
export interface Vocab {
  person: string;
  people: string;
  Person: string;
  People: string;
  resource: string;
  resources: string;
  Resource: string;
  Resources: string;
  org: string;
  Org: string;
  visit: string;
  visits: string;
  Visit: string;
  Visits: string;
}

const WORDS: Record<string, [string, string, string, string, string]> = {
  // person, people, resource, org, visit
  clinic: ["patient", "patients", "doctor", "clinic", "visit"],
  institute: ["student", "students", "teacher", "institute", "session"],
  business: ["customer", "customers", "staff member", "business", "visit"],
};

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export function vocabFor(type: string | undefined | null): Vocab {
  const [person, people, resource, org, visit] = WORDS[type || "clinic"] || WORDS.clinic;
  const resources = resource === "staff member" ? "staff" : `${resource}s`;
  return {
    person,
    people,
    Person: cap(person),
    People: cap(people),
    resource,
    resources,
    Resource: cap(resource),
    Resources: cap(resources),
    org,
    Org: cap(org),
    visit,
    visits: `${visit}s`,
    Visit: cap(visit),
    Visits: cap(`${visit}s`),
  };
}

export function useVocab(): Vocab {
  const { business } = useBusiness();
  return vocabFor(business?.type);
}
