import { Client, RequestManager, WebSocketTransport } from "@open-rpc/client-js";
import { Lock } from "semaphore-async-await";

export type RequestObject = Parameters<Client["request"]>[0];

/**
 * A client wrapper which retrieves the server address from the backend and
 * automatically re-establishes the connection to the server when it drops.
 */
export class RClient {
  readonly #clientInitialisationLock = new Lock();

  #handle?: [Client, WebSocketTransport];

  get client(): Promise<Client> {
    return this.#clientInitialisationLock.execute(() => {
      let runningClient: Client | undefined;

      if (this.#handle) {
        const [client, transport] = this.#handle;
        if (![WebSocket.CLOSING, WebSocket.CLOSED].includes(transport.connection.readyState)) {
          runningClient = client;
        }
      }

      if (!runningClient) {
        const transport = new WebSocketTransport(`ws://${location.host}/api`),
          requestManager = new RequestManager([transport]);
        runningClient = new Client(requestManager);
        this.#handle = [runningClient, transport];
      }

      return runningClient;
    });
  }
}
