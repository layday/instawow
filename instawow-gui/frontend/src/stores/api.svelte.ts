import { JSONRPCError } from "@open-rpc/client-js";
import { Api } from "../api";
import { RClient, type RequestObject } from "../ipc";
import { ANY_PROFILE, type AlertsRef } from "./alerts.svelte";

class ProfileApi extends Api {
  #alertOnJsonRpcError(requestObject: RequestObject, error: unknown) {
    if (error instanceof JSONRPCError) {
      const activeProfile = (requestObject.params as any)?.["profile"] ?? ANY_PROFILE;

      this.alertsRef.value[activeProfile] = [
        { heading: error.message, message: JSON.stringify(error.data) },
        ...(this.alertsRef.value[activeProfile] ?? []),
      ];
    }
  }

  constructor(
    api: Api,
    profile: string,
    private alertsRef: AlertsRef,
  ) {
    super(api.clientWrapper, profile);
  }

  async request(requestObject: RequestObject) {
    try {
      return await super.request(requestObject);
    } catch (error) {
      this.#alertOnJsonRpcError(requestObject, error);
      throw error;
    }
  }
}

export const API_KEY = "API";

export const makeApi = () => new Api(new RClient());

export { ProfileApi as Api };
