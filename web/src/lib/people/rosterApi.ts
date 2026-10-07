import type { Person } from './types';

/** One write to the people registry; the saved person comes back, or null when the server refused. */
export async function sendPerson(method: string, path: string, body: unknown): Promise<Person | null> {
  const response = await fetch(`/api/v1/roster${path}`, {
    method,
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  return response.ok ? ((await response.json()) as Person) : null;
}

export const personPath = (person: Person, rest = '') => `/${encodeURIComponent(person.person_id)}${rest}`;

type Answer = { kind: string; target_id: string; decision: string | null };

/** Role, notes and answers to the scan's guesses. A change of null clears the field, so `??` would keep the old value. */
export const savePerson = (person: Person, changes: Partial<Person> = {}, links: Answer[] = []) =>
  sendPerson('PUT', personPath(person), {
    role: 'role' in changes ? changes.role : (person.role ?? null),
    notes: 'notes' in changes ? changes.notes : (person.notes ?? null),
    links,
  });
