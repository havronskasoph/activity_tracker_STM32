import { pairDevice, type Bluetooth, type BluetoothDevice } from "./bluetooth";
import { FormEvent, ReactNode, useEffect, useState, useCallback, useRef } from "react";
import {
  api,
  ApiError,
  type User,
  type Profile,
  type Device,
  type Summary,
  type ActivityDay,
} from "./api";

type IconName =
  | "activity"
  | "battery"
  | "bluetooth"
  | "chevron"
  | "close"
  | "dashboard"
  | "device"
  | "logout"
  | "profile"
  | "steps";

function Icon({ name, className = "h-5 w-5" }: { name: IconName; className?: string }) {
  const paths: Record<IconName, ReactNode> = {
    activity: <path d="M3 12h4l2.5-7 5 14 2.5-7h4" />,
    battery: (
      <>
        <rect x="3" y="7" width="16" height="10" rx="2" />
        <path d="M21 10v4M6 10h7" />
      </>
    ),
    bluetooth: <path d="m7 7 10 10-5 4V3l5 4L7 17" />,
    chevron: <path d="m9 18 6-6-6-6" />,
    close: <path d="m6 6 12 12M18 6 6 18" />,
    dashboard: (
      <>
        <rect x="3" y="3" width="7" height="7" rx="2" />
        <rect x="14" y="3" width="7" height="7" rx="2" />
        <rect x="3" y="14" width="7" height="7" rx="2" />
        <rect x="14" y="14" width="7" height="7" rx="2" />
      </>
    ),
    device: (
      <>
        <rect x="7" y="2.5" width="10" height="19" rx="3" />
        <path d="M10 6h4M11 18h2" />
      </>
    ),
    logout: (
      <>
        <path d="M10 17l5-5-5-5M15 12H3" />
        <path d="M14 4h5a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-5" />
      </>
    ),
    profile: (
      <>
        <circle cx="12" cy="8" r="4" />
        <path d="M4 21a8 8 0 0 1 16 0" />
      </>
    ),
    steps: (
      <>
        <path d="M8 13c-2 0-4 2-4 4s2 3 4 2 3-4 2-5c-.4-.7-1.2-1-2-1ZM15 4c-2 0-3 2-3 4s1 3 3 3 4-1 4-3-2-4-4-4Z" />
      </>
    ),
  };
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [registering, setRegistering] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [profile, setProfile] = useState<Profile>({});
  const [devices, setDevices] = useState<Device[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [history, setHistory] = useState<ActivityDay[]>([]);
  const [loadingData, setLoadingData] = useState(false);
  const [dataReady, setDataReady] = useState(false);
  const [page, setPage] = useState<"dashboard" | "profile">("dashboard");
  const [showPassword, setShowPassword] = useState(false);
  const [connectOpen, setConnectOpen] = useState(false);
  const [saved, setSaved] = useState(false);
  const [mobileMenu, setMobileMenu] = useState(false);
  const [bluetoothName, setBluetoothName] = useState("");
  const [pairing, setPairing] = useState(false);
  const bluetoothDevice = useRef<BluetoothDevice | null>(null);
  const pairAttempt = useRef(0);
  const disconnectBluetooth = useCallback(() => {
    pairAttempt.current++;
    bluetoothDevice.current?.gatt?.disconnect();
    bluetoothDevice.current = null;
    setBluetoothName("");
  }, []);

  useEffect(() => {
    if (!user) disconnectBluetooth();
    return disconnectBluetooth;
  }, [user, disconnectBluetooth]);

  const handleError = useCallback((cause: unknown) => {
    if (cause instanceof ApiError && cause.status === 401) {
      setUser(null);
      setProfile({});
      setDevices([]);
      setSummary(null);
      setHistory([]);
      setDataReady(false);
      setConnectOpen(false);
    }
    setError(cause instanceof Error ? cause.message : "Something went wrong. Please try again.");
  }, []);

  useEffect(() => {
    let active = true;
    api<{ user: User }>("/auth/me")
      .then((result) => {
        if (active) setUser(result.user);
      })
      .catch((cause) => {
        if (active && !(cause instanceof ApiError && cause.status === 401)) handleError(cause);
      })
      .finally(() => {
        if (active) setCheckingSession(false);
      });
    return () => {
      active = false;
    };
  }, [handleError]);

  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      setLoadingData(true);
      // Today uses local midnight. Weekly bars are explicitly grouped by UTC date.
      const now = new Date();
      const midnight = new Date(now);
      midnight.setHours(0, 0, 0, 0);
      const weekStart = new Date(now);
      weekStart.setUTCHours(0, 0, 0, 0);
      weekStart.setUTCDate(weekStart.getUTCDate() - 6);
      const range = (from: Date) =>
        `?from=${encodeURIComponent(from.toISOString())}&to=${encodeURIComponent(now.toISOString())}`;
      try {
        const [p, d, total, h] = await Promise.all([
          api<{ profile: Profile }>("/profile"),
          api<{ devices: Device[] }>("/devices"),
          api<Summary>("/activity/summary" + range(midnight)),
          api<{ days: ActivityDay[] }>("/activity/history" + range(weekStart)),
        ]);
        if (signal?.aborted) return;
        setProfile(p.profile);
        setDevices(d.devices);
        setSummary(total);
        setHistory(h.days);
        setDataReady(true);
      } catch (cause) {
        if (!signal?.aborted) handleError(cause);
      } finally {
        if (!signal?.aborted) setLoadingData(false);
      }
    },
    [handleError],
  );

  useEffect(() => {
    if (!user) return;
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [user, refresh]);

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      const result = await api<{ user: User }>(
        registering ? "/auth/register" : "/auth/login",
        "POST",
        {
          email: form.get("email"),
          password: form.get("password"),
        },
      );
      setUser(result.user);
      setDataReady(false);
      setPage("dashboard");
      setSaved(false);
    } catch (cause) {
      handleError(cause);
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    setBusy(true);
    setError("");
    try {
      await api("/auth/logout", "POST", {});
      setUser(null);
      setProfile({});
      setDevices([]);
      setSummary(null);
      setHistory([]);
      setDataReady(false);
      setPage("dashboard");
      setConnectOpen(false);
      setMobileMenu(false);
    } catch (cause) {
      handleError(cause);
    } finally {
      setBusy(false);
    }
  }

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setSaved(false);
    const values = Object.fromEntries(new FormData(event.currentTarget));
    const payload: Record<string, string | number> = {};
    for (const [key, value] of Object.entries(values)) {
      if (["heightCm", "weightKg", "dailyStepGoal"].includes(key)) {
        if (value !== "") payload[key] = Number(value);
      } else payload[key] = String(value);
    }
    try {
      const result = await api<{ profile: Profile }>("/profile", "PATCH", payload);
      setProfile(result.profile);
      setSaved(true);
    } catch (cause) {
      handleError(cause);
    } finally {
      setBusy(false);
    }
  }

  const displayName =
    [profile.firstName, profile.lastName].filter(Boolean).join(" ") || user?.email || "";
  const initials = (profile.firstName?.[0] || user?.email[0] || "") + (profile.lastName?.[0] || "");
  const goal = profile.dailyStepGoal || 10000;
  const steps = summary?.steps || 0;
  const percent = Math.round((steps / goal) * 100);
  const days = Array.from({ length: 7 }, (_, index) => {
    const day = new Date();
    day.setUTCDate(day.getUTCDate() - 6 + index);
    const count = history.find((item) => item.date === day.toISOString().slice(0, 10))?.steps || 0;
    return {
      day: day.toLocaleDateString(undefined, { weekday: "short", timeZone: "UTC" }),
      steps: count,
      value: Math.min(100, (count / Math.max(goal, ...history.map((item) => item.steps))) * 100),
    };
  });

  if (checkingSession)
    return (
      <main className="grid min-h-screen place-items-center" role="status">
        Checking your session...
      </main>
    );

  if (!user) {
    return (
      <main className="min-h-screen bg-[#f4f7f4] text-[#15221c] lg:grid lg:grid-cols-[1.08fr_.92fr]">
        <section className="relative hidden min-h-screen overflow-hidden bg-[#10261d] p-14 text-white lg:flex lg:flex-col lg:justify-between">
          <div className="absolute -right-36 -top-40 h-[520px] w-[520px] rounded-full border border-white/10" />
          <div className="absolute -right-16 -top-20 h-[350px] w-[350px] rounded-full border border-white/10" />
          <div className="absolute bottom-20 left-28 h-52 w-52 rounded-full bg-[#a8e063]/10 blur-3xl" />
          <div className="relative flex items-center gap-3">
            <div className="grid h-11 w-11 place-items-center rounded-xl bg-[#a8e063] text-[#173023]">
              <Icon name="activity" />
            </div>
            <span className="text-xl font-bold tracking-tight">spokiy</span>
          </div>
          <div className="relative max-w-xl pb-10">
            <div className="mb-8 flex h-64 items-end gap-3 rounded-[28px] border border-white/10 bg-white/[0.04] p-8 backdrop-blur">
              {[42, 61, 53, 78, 67, 91, 76, 100, 83].map((height, index) => (
                <div key={index} className="flex-1 rounded-full bg-white/10 p-1">
                  <div
                    className="w-full rounded-full bg-gradient-to-t from-[#70bd55] to-[#b4ea6c]"
                    style={{ height: `${height * 1.7}px` }}
                  />
                </div>
              ))}
            </div>
            <p className="mb-4 text-sm font-semibold uppercase tracking-[.2em] text-[#a8e063]">
              Powered by STM32
            </p>
            <h1 className="text-5xl font-semibold leading-[1.08] tracking-[-.04em]">
              Move better.
              <br />
              Know your body.
            </h1>
            <p className="mt-6 max-w-md text-lg leading-8 text-white/60">
              Your daily activity, health insights, and progress—captured precisely from your
              wearable.
            </p>
          </div>
        </section>

        <section className="flex min-h-screen items-center justify-center px-6 py-12 sm:px-12">
          <div className="w-full max-w-[430px]">
            <div className="mb-12 flex items-center gap-3 lg:hidden">
              <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#214f39] text-white">
                <Icon name="activity" />
              </div>
              <span className="text-xl font-bold">spokiy</span>
            </div>
            <div className="mb-9">
              <p className="mb-3 text-sm font-semibold uppercase tracking-[.18em] text-[#4d7c5d]">
                {registering ? "Get started" : "Welcome back"}
              </p>
              <h2 className="text-4xl font-semibold tracking-[-.04em]">
                {registering ? "Create your account" : "Sign in to your account"}
              </h2>
              <p className="mt-3 text-[#68746e]">Continue tracking your movement and progress.</p>
            </div>
            {error && (
              <p role="alert" className="mb-4 rounded-xl bg-red-50 p-3 text-sm text-red-800">
                {error}
              </p>
            )}
            <form onSubmit={login} className="space-y-5">
              <label className="block">
                <span className="mb-2 block text-sm font-semibold">Email address</span>
                <input
                  required
                  type="email"
                  name="email"
                  autoComplete="email"
                  className="w-full rounded-xl border border-[#d9e0dc] bg-white px-4 py-3.5 outline-none transition focus:border-[#346b4b] focus:ring-4 focus:ring-[#346b4b]/10"
                />
              </label>
              <label className="block">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-sm font-semibold">Password</span>
                </div>
                <div className="relative">
                  <input
                    required
                    type={showPassword ? "text" : "password"}
                    name="password"
                    minLength={12}
                    maxLength={128}
                    autoComplete={registering ? "new-password" : "current-password"}
                    className="w-full rounded-xl border border-[#d9e0dc] bg-white px-4 py-3.5 pr-16 outline-none transition focus:border-[#346b4b] focus:ring-4 focus:ring-[#346b4b]/10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute inset-y-0 right-4 text-xs font-bold uppercase tracking-wider text-[#66736d]"
                  >
                    {showPassword ? "Hide" : "Show"}
                  </button>
                </div>
              </label>
              <p className="text-sm text-[#54615b]">
                Use at least 12 characters. Sessions last seven days.
              </p>
              <button
                disabled={busy}
                className="disabled:opacity-50 w-full rounded-xl bg-[#214f39] py-4 font-semibold text-white shadow-lg shadow-[#214f39]/15 transition hover:bg-[#183c2b]"
              >
                {busy ? "Please wait..." : registering ? "Create account" : "Sign in"}
              </button>
            </form>
            <p className="mt-8 text-center text-sm text-[#6c7772]">
              {registering ? "Already have an account?" : "New to spokiy?"}{" "}
              <button
                disabled={busy}
                onClick={() => {
                  setRegistering(!registering);
                  setError("");
                }}
                className="font-bold text-[#285b40] hover:underline"
              >
                {registering ? "Sign in" : "Create an account"}
              </button>
            </p>
          </div>
        </section>
      </main>
    );
  }

  return (
    <div className="min-h-screen bg-[#f5f7f5] text-[#18251f]">
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-64 flex-col bg-[#11291f] p-5 text-white transition-transform lg:translate-x-0 ${mobileMenu ? "translate-x-0" : "-translate-x-full"}`}
      >
        <div className="mb-12 flex items-center gap-3 px-2 pt-2">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#a8e063] text-[#173023]">
            <Icon name="activity" />
          </div>
          <span className="text-xl font-bold tracking-tight">spokiy</span>
          <button onClick={() => setMobileMenu(false)} className="ml-auto lg:hidden">
            <Icon name="close" />
          </button>
        </div>
        <nav className="space-y-2">
          {[
            { id: "dashboard" as const, label: "Overview", icon: "dashboard" as const },
            { id: "profile" as const, label: "My profile", icon: "profile" as const },
          ].map((item) => (
            <button
              key={item.id}
              onClick={() => {
                setPage(item.id);
                setMobileMenu(false);
              }}
              className={`flex w-full items-center gap-3 rounded-xl px-4 py-3 text-sm font-semibold transition ${page === item.id ? "bg-white/12 text-white" : "text-white/55 hover:bg-white/5 hover:text-white"}`}
            >
              <Icon name={item.icon} className="h-5 w-5" />
              {item.label}
            </button>
          ))}
        </nav>
        <div className="mt-auto">
          <div className="mb-4 rounded-2xl border border-white/10 bg-white/5 p-4">
            <div className="mb-3 flex items-center justify-between">
              <span className="text-xs font-medium text-white/50">DEVICE STATUS</span>
              <span
                className={`h-2 w-2 rounded-full ${bluetoothName ? "bg-[#a8e063]" : "bg-white/25"}`}
              />
            </div>
            <p className="text-sm font-semibold">{bluetoothName || "No device connected"}</p>
            <button
              onClick={() => setConnectOpen(true)}
              className="mt-1 text-xs font-semibold text-[#a8e063]"
            >
              {bluetoothName ? "Manage device" : "Connect now"}
            </button>
          </div>
          <button
            onClick={logout}
            disabled={busy}
            className="flex w-full items-center gap-3 px-4 py-3 text-sm font-semibold text-white/50 hover:text-white"
          >
            <Icon name="logout" />
            Sign out
          </button>
        </div>
      </aside>

      <main className="min-h-screen lg:ml-64">
        <header className="flex h-20 items-center justify-between border-b border-[#e2e7e3] bg-white/80 px-5 backdrop-blur sm:px-8 lg:px-10">
          <button
            onClick={() => setMobileMenu(true)}
            className="grid h-10 w-10 place-items-center rounded-xl border border-[#dfe5e1] lg:hidden"
          >
            <span className="text-xl">☰</span>
          </button>
          <div className="hidden sm:block">
            <p className="text-xs font-semibold uppercase tracking-[.15em] text-[#7a857f]">
              {page === "dashboard"
                ? new Date().toLocaleDateString(undefined, {
                    weekday: "long",
                    month: "long",
                    day: "numeric",
                  })
                : "Account"}
            </p>
            <h1 className="mt-1 text-xl font-bold">
              {page === "dashboard" ? `Hello, ${profile.firstName || user.email}` : "Your profile"}
            </h1>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <button
              onClick={() => setConnectOpen(true)}
              className={`hidden items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold sm:flex ${bluetoothName ? "bg-[#e9f4e9] text-[#2e6343]" : "bg-[#214f39] text-white"}`}
            >
              <Icon name="bluetooth" className="h-4 w-4" />
              {bluetoothName || "Connect device"}
            </button>
            <button
              onClick={() => setPage("profile")}
              className="grid h-11 w-11 place-items-center rounded-full bg-[#dce9df] text-sm font-bold text-[#28573d]"
            >
              {initials.toUpperCase()}
            </button>
          </div>
        </header>

        <div className="px-5 pt-4 sm:px-8 lg:px-10">
          {error && (
            <p role="alert" className="rounded-xl bg-red-50 p-3 text-red-800">
              {error}
            </p>
          )}
          {loadingData && <p role="status">Loading your data...</p>}
          <button
            disabled={loadingData || busy}
            onClick={() => {
              setError("");
              void refresh();
            }}
            className="mt-2 text-sm font-semibold text-[#28573d]"
          >
            Refresh data
          </button>
          {summary?.samples === 0 && (
            <p className="mt-2 text-sm text-[#748078]">
              No measurements today. Connect your tracker to get started.
            </p>
          )}
        </div>
        {page === "profile" && !dataReady ? (
          <p className="p-8">Your profile has not loaded. Use Refresh data to retry.</p>
        ) : page === "dashboard" ? (
          <div className="mx-auto max-w-[1380px] p-5 sm:p-8 lg:p-10">
            <section className="mb-8 overflow-hidden rounded-[28px] bg-[#183d2c] text-white">
              <div className="grid items-center gap-8 p-7 sm:p-9 lg:grid-cols-[1fr_auto]">
                <div>
                  <div className="mb-5 flex items-center gap-2 text-sm text-white/60">
                    <span className="h-2 w-2 rounded-full bg-[#a8e063]" />
                    Today's progress
                  </div>
                  <div className="flex flex-wrap items-end gap-x-12 gap-y-5">
                    <div>
                      <p className="text-5xl font-semibold tracking-[-.05em]">
                        {summary ? steps.toLocaleString() : "--"}
                      </p>
                      <p className="mt-2 text-sm text-white/55">
                        of {goal.toLocaleString()} daily steps
                      </p>
                    </div>
                    <div className="pb-1">
                      <p className="text-2xl font-semibold">{summary ? `${percent}%` : "--"}</p>
                      <p className="mt-1 text-xs text-white/45">Goal completed</p>
                    </div>
                  </div>
                  <div className="mt-7 h-2 max-w-2xl overflow-hidden rounded-full bg-white/10">
                    <div
                      className="h-full rounded-full bg-[#a8e063]"
                      style={{ width: `${Math.min(100, percent)}%` }}
                    />
                  </div>
                </div>
                <div className="relative mx-auto grid h-36 w-36 place-items-center rounded-full border-[9px] border-white/10">
                  <div className="text-center">
                    <Icon name="steps" className="mx-auto h-7 w-7 text-[#a8e063]" />
                    <span className="mt-1 block text-xs text-white/55">
                      {Math.max(0, goal - steps).toLocaleString()} to go
                    </span>
                  </div>
                </div>
              </div>
            </section>

            <section className="grid gap-6 xl:grid-cols-[1.55fr_1fr]">
              <article className="rounded-2xl border border-[#e3e8e4] bg-white p-6">
                <div className="mb-8 flex items-center justify-between">
                  <div>
                    <h2 className="font-bold">Weekly activity</h2>
                    <p className="mt-1 text-sm text-[#7a857f]">
                      Steps across the last 7 days (UTC)
                    </p>
                  </div>
                </div>
                <div className="flex h-52 items-end gap-3 sm:gap-5">
                  {days.map((day, index) => (
                    <div key={day.day} className="flex h-full flex-1 flex-col justify-end gap-3">
                      <div
                        className="relative flex-1 rounded-lg bg-[#f2f5f2]"
                        title={`${day.steps.toLocaleString()} steps`}
                      >
                        <div
                          className={`absolute inset-x-0 bottom-0 rounded-lg ${index === 6 ? "bg-[#214f39]" : "bg-[#a9d39d]"}`}
                          style={{ height: `${day.value}%` }}
                        />
                      </div>
                      <span className="text-center text-xs font-medium text-[#7b867f]">
                        {day.day}
                      </span>
                    </div>
                  ))}
                </div>
              </article>
              <article className="rounded-2xl border border-[#e3e8e4] bg-white p-6">
                <div className="mb-6 flex items-center justify-between">
                  <div>
                    <h2 className="font-bold">Device health</h2>
                    <p className="mt-1 text-sm text-[#7a857f]">
                      {bluetoothName || "No Bluetooth connection"}
                    </p>
                  </div>
                  <Icon name="device" className="text-[#50725e]" />
                </div>
                <p className="text-sm text-[#748078]">
                  {bluetoothName
                    ? "Connected over Bluetooth. Measurement syncing awaits firmware configuration."
                    : "Connect your tracker over Bluetooth."}{" "}
                  ({devices.length} saved devices)
                </p>
                <p className="mt-3 text-sm text-[#748078]">
                  Average heart rate today:{" "}
                  {summary?.averageHeartRate == null
                    ? "No readings"
                    : `${Math.round(summary.averageHeartRate)} bpm`}
                </p>
                <button
                  onClick={() => setConnectOpen(true)}
                  className="mt-6 rounded-xl bg-[#214f39] px-4 py-3 text-white"
                >
                  {bluetoothName ? "Manage device" : "Connect device"}
                </button>
              </article>
            </section>
          </div>
        ) : (
          <div className="mx-auto max-w-5xl p-5 sm:p-8 lg:p-10">
            <div className="mb-8">
              <h2 className="text-3xl font-semibold tracking-[-.03em]">Personal information</h2>
              <p className="mt-2 text-[#748078]">Manage your details and health preferences.</p>
            </div>
            <form
              key={JSON.stringify(profile)}
              onSubmit={saveProfile}
              onChange={() => setSaved(false)}
              className="overflow-hidden rounded-2xl border border-[#e1e7e2] bg-white"
            >
              <div className="flex flex-col gap-5 border-b border-[#e7ebe8] p-6 sm:flex-row sm:items-center">
                <div className="grid h-20 w-20 place-items-center rounded-full bg-[#dbeadd] text-xl font-bold text-[#28573d]">
                  {initials.toUpperCase()}
                </div>
                <div className="flex-1">
                  <h3 className="text-xl font-bold">{displayName}</h3>
                  <p className="mt-1 text-sm text-[#76827b]">
                    Member since {new Date(user.createdAt).toLocaleDateString()}
                  </p>
                </div>
              </div>
              <div className="grid gap-5 p-6 sm:grid-cols-2">
                {(
                  [
                    ["First name", "firstName", "text"],
                    ["Last name", "lastName", "text"],
                    ["Phone number", "phone", "tel"],
                    ["Date of birth", "dateOfBirth", "date"],
                    ["Location", "location", "text"],
                  ] as const
                ).map(([label, key, type]) => (
                  <label key={key} className="block">
                    <span className="mb-2 block text-sm font-semibold">{label}</span>
                    <input
                      name={key}
                      type={type}
                      maxLength={200}
                      defaultValue={String(profile[key] || "")}
                      className="w-full rounded-xl border border-[#dce2de] px-4 py-3"
                    />
                  </label>
                ))}
                <label className="block">
                  <span className="mb-2 block text-sm font-semibold">Email address</span>
                  <input
                    type="email"
                    value={user.email}
                    readOnly
                    className="w-full rounded-xl border border-[#dce2de] bg-gray-50 px-4 py-3"
                  />
                </label>
              </div>
              <div className="border-t border-[#e7ebe8] p-6">
                <h3 className="mb-5 font-bold">Health details</h3>
                <div className="grid gap-5 sm:grid-cols-3">
                  {(
                    [
                      ["Height (cm)", "heightCm", 30, 300],
                      ["Weight (kg)", "weightKg", 1, 700],
                      ["Daily step goal", "dailyStepGoal", 1, 1000000],
                    ] as const
                  ).map(([label, key, min, max]) => (
                    <label key={key}>
                      <span className="mb-2 block text-sm font-semibold">{label}</span>
                      <input
                        name={key}
                        type="number"
                        min={min}
                        max={max}
                        step={key === "dailyStepGoal" ? 1 : "any"}
                        required={key === "dailyStepGoal"}
                        defaultValue={profile[key] ?? ""}
                        className="w-full rounded-xl border border-[#dce2de] px-4 py-3"
                      />
                    </label>
                  ))}
                </div>
              </div>
              <div className="flex items-center justify-end gap-4 border-t border-[#e7ebe8] bg-[#fafbfa] p-5">
                {saved && (
                  <span className="text-sm font-semibold text-[#39704e]">Changes saved</span>
                )}
                <button
                  disabled={busy || !dataReady}
                  className="disabled:opacity-50 rounded-xl bg-[#214f39] px-6 py-3 text-sm font-semibold text-white"
                >
                  {busy ? "Saving..." : "Save changes"}
                </button>
              </div>
            </form>
          </div>
        )}
      </main>

      {connectOpen && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-[#0b1711]/55 p-4 backdrop-blur-sm">
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="devices-title"
            className="w-full max-w-md rounded-3xl bg-white p-6"
          >
            <div className="flex items-center justify-between">
              <h2 id="devices-title" className="text-xl font-bold">
                Connect a device
              </h2>
              <button
                aria-label="Close Bluetooth dialog"
                disabled={pairing}
                onClick={() => setConnectOpen(false)}
              >
                <Icon name="close" />
              </button>
            </div>
            <div className="py-6 text-center">
              <div className="mx-auto mb-5 grid h-20 w-20 place-items-center rounded-full bg-[#e6f2e7] text-[#347049]">
                <Icon name="bluetooth" className="h-9 w-9" />
              </div>
              <h3 className="text-lg font-bold">
                {bluetoothName ? `${bluetoothName} connected` : "Pair your STM32 device"}
              </h3>
              <p className="mt-3 text-sm text-[#748078]">
                {bluetoothName
                  ? "Bluetooth is connected. Activity syncing still needs your firmware service, characteristic and measurement format."
                  : "Keep your wearable nearby with Bluetooth enabled. Choose it in the browser Bluetooth window."}
              </p>
              {error && (
                <p role="alert" className="mt-4 text-sm text-red-800">
                  {error}
                </p>
              )}
              {bluetoothName ? (
                <button
                  onClick={disconnectBluetooth}
                  className="mt-6 w-full rounded-xl border py-3 text-[#a15050]"
                >
                  Disconnect device
                </button>
              ) : (
                <button
                  disabled={pairing || busy}
                  className="mt-6 w-full rounded-xl bg-[#214f39] py-3.5 font-semibold text-white disabled:opacity-50"
                  onClick={async () => {
                    setError("");
                    setPairing(true);
                    const attempt = ++pairAttempt.current;
                    let selected: BluetoothDevice | undefined;
                    try {
                      selected = await pairDevice(
                        (navigator as Navigator & { bluetooth?: Bluetooth }).bluetooth,
                        import.meta.env.VITE_BLE_SERVICE_UUID,
                      );
                      if (attempt !== pairAttempt.current) {
                        selected.gatt?.disconnect();
                        return;
                      }
                      const device = selected;
                      bluetoothDevice.current = device;
                      device.addEventListener(
                        "gattserverdisconnected",
                        () => {
                          if (bluetoothDevice.current === device) {
                            bluetoothDevice.current = null;
                            setBluetoothName("");
                          }
                        },
                        { once: true },
                      );
                      await api("/devices", "POST", {
                        identifier: device.id,
                        name: device.name || "STM32 tracker",
                      });
                      if (attempt !== pairAttempt.current) {
                        device.gatt?.disconnect();
                        return;
                      }
                      if (!device.gatt?.connected)
                        throw new Error("Device disconnected while connecting. Please try again.");
                      setBluetoothName(device.name || "STM32 tracker");
                      await refresh();
                    } catch (cause) {
                      selected?.gatt?.disconnect();
                      if (attempt === pairAttempt.current) {
                        bluetoothDevice.current = null;
                        setBluetoothName("");
                        if (!(cause instanceof DOMException && cause.name === "NotFoundError"))
                          handleError(cause);
                      }
                    } finally {
                      setPairing(false);
                    }
                  }}
                >
                  {pairing ? "Connecting..." : "Find Bluetooth devices"}
                </button>
              )}
              <p className="mt-4 text-xs text-[#748078]">
                Use Chrome or Edge on localhost or HTTPS. Your tracker must support Bluetooth Low
                Energy (BLE).
              </p>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

export default App;
