import { JSONRPCError } from "@open-rpc/client-js";
import { Api, type InternalError } from "../api";
import { RClient, type RequestObject } from "../ipc";
import { ANY_PROFILE, alerts } from "./alerts";
import { get, readable } from "svelte/store";
import { activeProfile as activeProfileRef } from "./profiles";

class AlertOnErrorApi extends Api {
  #isInternalError(object: unknown): object is InternalError {
    return !!object && typeof object === "object" && "traceback_exception" in object;
  }

  #alertOnJsonRpcError(error: unknown) {
    if (error instanceof JSONRPCError && this.#isInternalError(error.data)) {
      const activeProfile = get(activeProfileRef) ?? ANY_PROFILE;
      const message = error.data.traceback_exception.filter(Boolean).slice(-1).join("");
      alerts.update((p) => ({
        ...p,
        [activeProfile]: [{ heading: error.message, message }, ...(p[activeProfile] ?? [])],
      }));
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

export const api = readable(new AlertOnErrorApi(new RClient()));
