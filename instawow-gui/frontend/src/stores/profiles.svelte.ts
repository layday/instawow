import type { Config } from "../api";

export type ProfilesRef = ReturnType<typeof makeProfiles>;

export const PROFILES_KEY = "PROFILES";

export const makeProfiles = () => {
  let profiles = $state<Record<string, Config>>({});

  return {
    get value() {
      return profiles;
    },
    set value(value: typeof profiles) {
      profiles = value;
    },
  };
};

export type ActiveProfileRef = ReturnType<typeof makeActiveProfile>;

export const ACTIVE_PROFILE_KEY = "ACTIVE_PROFILE";

export const makeActiveProfile = () => {
  let profile = $state<string>();

  return {
    get value() {
      return profile;
    },
    set value(value: typeof profile) {
      profile = value;
    },
  };
};
