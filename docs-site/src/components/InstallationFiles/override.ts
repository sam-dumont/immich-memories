export function installationOverride(version: string, released: boolean): string {
  const tag = released ? version.replace(/^v/, '') : 'development';
  const app = released
    ? `ghcr.io/sam-dumont/immich-video-memory-generator:${tag}`
    : 'immich-memories:development';
  return `services:
  immich-memories:
    image: ${app}
  immich-memories-inference:
    image: ghcr.io/sam-dumont/immich-video-memory-generator/inference:\${INFERENCE_TAG:-${released ? tag : 'latest'}}`;
}
