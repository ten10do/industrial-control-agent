import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { UserManager, WebStorageStateStore } from "oidc-client-ts";

import { setAccessTokenProvider } from "./api";


const authority = import.meta.env.VITE_OIDC_AUTHORITY?.trim().replace(/\/$/, "") || "";
const clientId = import.meta.env.VITE_OIDC_CLIENT_ID?.trim() || "";
const authEnabled = Boolean(authority && clientId);
const hasPartialConfiguration = Boolean(authority || clientId) && !authEnabled;
const authenticationRequired = import.meta.env.PROD || authEnabled || hasPartialConfiguration;

const defaultAuth = {
  enabled: false,
  ready: true,
  user: null,
  error: "",
  login: async () => {},
  logout: async () => {},
};

const AuthContext = createContext(defaultAuth);


function buildUserManager() {
  if (!authEnabled) {
    return null;
  }
  const origin = window.location.origin;
  return new UserManager({
    authority,
    client_id: clientId,
    redirect_uri: import.meta.env.VITE_OIDC_REDIRECT_URI?.trim() || `${origin}/`,
    post_logout_redirect_uri: (
      import.meta.env.VITE_OIDC_POST_LOGOUT_REDIRECT_URI?.trim() || `${origin}/`
    ),
    response_type: "code",
    scope: import.meta.env.VITE_OIDC_SCOPE?.trim() || "openid profile",
    automaticSilentRenew: true,
    loadUserInfo: true,
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
  });
}


function hasSigninResponse() {
  const parameters = new URLSearchParams(window.location.search);
  return parameters.has("code") && parameters.has("state");
}


export function AuthProvider({ children }) {
  const manager = useMemo(buildUserManager, []);
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(!authEnabled);
  const [error, setError] = useState(
    hasPartialConfiguration
      ? "OIDC 配置不完整：必须同时配置 Authority 和 Client ID。"
      : import.meta.env.PROD && !authEnabled
        ? "生产构建缺少 OIDC 配置，系统已拒绝匿名访问。"
      : "",
  );

  useEffect(() => {
    if (!manager) {
      setAccessTokenProvider(() => "");
      return undefined;
    }

    let active = true;
    const updateUser = (nextUser) => {
      if (active) {
        setUser(nextUser && !nextUser.expired ? nextUser : null);
      }
    };
    const clearUser = () => updateUser(null);
    manager.events.addUserLoaded(updateUser);
    manager.events.addUserUnloaded(clearUser);
    manager.events.addAccessTokenExpired(clearUser);

    async function initialize() {
      try {
        const nextUser = hasSigninResponse()
          ? await manager.signinCallback()
          : await manager.getUser();
        if (hasSigninResponse()) {
          window.history.replaceState({}, document.title, window.location.pathname);
        }
        updateUser(nextUser);
      } catch {
        if (active) {
          setError("登录回调校验失败，请重新登录。");
        }
      } finally {
        if (active) {
          setReady(true);
        }
      }
    }
    initialize();

    return () => {
      active = false;
      manager.events.removeUserLoaded(updateUser);
      manager.events.removeUserUnloaded(clearUser);
      manager.events.removeAccessTokenExpired(clearUser);
      setAccessTokenProvider(() => "");
    };
  }, [manager]);

  useEffect(() => {
    setAccessTokenProvider(() => user?.access_token || "");
  }, [user]);

  const value = useMemo(
    () => ({
      enabled: authenticationRequired,
      ready,
      user,
      error,
      login: async () => {
        setError("");
        await manager?.signinRedirect();
      },
      logout: async () => {
        setError("");
        if (manager) {
          await manager.signoutRedirect();
        }
      },
    }),
    [error, manager, ready, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}


export function useAuth() {
  return useContext(AuthContext);
}
