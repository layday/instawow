import { RequestManager, Client, WebSocketTransport } from "@open-rpc/client-js";
import { Lock } from "semaphore-async-await";

// A client wrapper which retrieves the server address from the backend and
// automatically re-establishes the connection to the server when it drops.
export const getClient = () => {
  const connectToServer = async () => {
    const transport = new WebSocketTransport(`ws://${location.host}/api`);
    const client = new Client(new RequestManager([transport]));
    return [transport, client] as const;
  };

  const clientInitialisationLock = new Lock();

  let transportS: WebSocketTransport;
  let clientS: Client;

  return () =>
    clientInitialisationLock.execute(async () => {
      if (
        typeof clientS === "undefined" ||
        [WebSocket.CLOSING, WebSocket.CLOSED].includes(transportS.connection.readyState)
      ) {
        [transportS, clientS] = await connectToServer();
      }
      return clientS;
    });
};
