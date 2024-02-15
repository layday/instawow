import { JSONRPCError } from "@open-rpc/client-js";
import { getContext } from "svelte";
import { Api, type InternalError } from "../api";
import { RClient, type RequestObject } from "../ipc";
import { ALERTS_KEY, ANY_PROFILE, type AlertsRef } from "./alerts.svelte";
import { ACTIVE_PROFILE_KEY, type ActiveProfileRef } from "./profiles.svelte";

class ProfileApi extends Api {
  #isInternalError(object: unknown): object is InternalError {
    return !!object && typeof object === "object" && "traceback_exception" in object;
  }

  #alertOnJsonRpcError(error: unknown) {
    if (error instanceof JSONRPCError && this.#isInternalError(error.data)) {
      const activeProfileRef = getContext<ActiveProfileRef>(ACTIVE_PROFILE_KEY);
      const alertsRef = getContext<AlertsRef>(ALERTS_KEY);

      const activeProfile = activeProfileRef.value ?? ANY_PROFILE;

      const message = error.data.traceback_exception.filter(Boolean).slice(-1).join("");

      alertsRef.value = {
        ...alertsRef.value,
        [activeProfile]: [
          { heading: error.message, message },
          ...(alertsRef.value[activeProfile] ?? []),
        ],
      };
    }
  }

  async request(requestObject: RequestObject) {
    try {
      return await super.request(requestObject);
    } catch (error) {
      this.#alertOnJsonRpcError(error);
      throw error;
    }
  }
}

export const API_KEY = "API";

export const makeApi = () => new ProfileApi(new RClient());

export { Api };
