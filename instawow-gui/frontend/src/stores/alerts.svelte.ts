export type AlertsRef = ReturnType<typeof makeAlerts>;

export interface Alert {
  heading: string;
  message: string;
}

export const ANY_PROFILE: unique symbol = Symbol("*");

export const ALERTS_KEY = "ALERTS";

export const makeAlerts = () => {
  const initialValue = { [ANY_PROFILE]: [] };

  let alerts = $state<Record<typeof ANY_PROFILE | string, Alert[]>>({ ...initialValue });

  return {
    get value() {
      return alerts;
    },
    set value(value: typeof alerts) {
      alerts = value;
    },
    reset() {
      alerts = { ...initialValue };
    },
  };
};
