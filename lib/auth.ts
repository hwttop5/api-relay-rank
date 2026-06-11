import { getServerSession, type NextAuthOptions, type Session } from "next-auth";
import GitHubProvider from "next-auth/providers/github";

import { hasDatabaseUrl, upsertGithubUser } from "./postgres";
import type { AuthenticatedGithubUser } from "./types";

function githubClientId() {
  return process.env.GITHUB_ID?.trim() || "";
}

function githubClientSecret() {
  return process.env.GITHUB_SECRET?.trim() || "";
}

export function isGithubAuthConfigured() {
  return Boolean(githubClientId() && githubClientSecret() && process.env.NEXTAUTH_SECRET?.trim());
}

function readProfileValue(profile: unknown, key: string) {
  if (!profile || typeof profile !== "object") {
    return "";
  }
  const value = (profile as Record<string, unknown>)[key];
  return String(value ?? "").trim();
}

function githubUserFromToken(token: Record<string, unknown>): AuthenticatedGithubUser | null {
  const githubId = String(token.githubId || "").trim();
  const githubLogin = String(token.githubLogin || "").trim();
  if (!githubId || !githubLogin) {
    return null;
  }
  return {
    githubId,
    githubLogin,
    name: String(token.name || "").trim() || null,
    avatarUrl: String(token.picture || token.avatarUrl || "").trim() || null,
    profileUrl: String(token.profileUrl || "").trim() || null,
  };
}

export const authOptions: NextAuthOptions = {
  session: {
    strategy: "jwt",
  },
  providers: isGithubAuthConfigured()
    ? [
        GitHubProvider({
          clientId: githubClientId(),
          clientSecret: githubClientSecret(),
        }),
      ]
    : [],
  callbacks: {
    async signIn({ account, profile }) {
      if (account?.provider !== "github") {
        return false;
      }
      const githubId = String(account.providerAccountId || readProfileValue(profile, "id")).trim();
      const githubLogin = readProfileValue(profile, "login");
      if (!githubId || !githubLogin) {
        return false;
      }
      if (hasDatabaseUrl()) {
        await upsertGithubUser({
          githubId,
          githubLogin,
          name: readProfileValue(profile, "name") || null,
          avatarUrl: readProfileValue(profile, "avatar_url") || null,
          profileUrl: readProfileValue(profile, "html_url") || `https://github.com/${githubLogin}`,
        });
      }
      return true;
    },
    async jwt({ token, account, profile }) {
      if (account?.provider === "github") {
        const githubLogin = readProfileValue(profile, "login");
        token.githubId = String(account.providerAccountId || readProfileValue(profile, "id")).trim();
        token.githubLogin = githubLogin;
        token.avatarUrl = readProfileValue(profile, "avatar_url") || token.picture;
        token.profileUrl = readProfileValue(profile, "html_url") || (githubLogin ? `https://github.com/${githubLogin}` : "");
      }
      return token;
    },
    async session({ session, token }) {
      const user = githubUserFromToken(token as Record<string, unknown>);
      if (session.user && user) {
        const sessionUser = session.user as typeof session.user & {
          githubId?: string;
          githubLogin?: string;
          profileUrl?: string | null;
        };
        sessionUser.githubId = user.githubId;
        sessionUser.githubLogin = user.githubLogin;
        sessionUser.profileUrl = user.profileUrl;
        sessionUser.name = user.name || user.githubLogin;
        sessionUser.image = user.avatarUrl;
      }
      return session;
    },
  },
};

export async function auth() {
  return getServerSession(authOptions);
}

export async function getAuthenticatedGithubUser(): Promise<AuthenticatedGithubUser | null> {
  const session = await auth();
  const sessionUser = session?.user as (Session["user"] & {
    githubId?: string;
    githubLogin?: string;
    profileUrl?: string | null;
  }) | undefined;
  const githubId = String(sessionUser?.githubId || "").trim();
  const githubLogin = String(sessionUser?.githubLogin || "").trim();
  if (!githubId || !githubLogin) {
    return null;
  }
  return {
    githubId,
    githubLogin,
    name: sessionUser?.name || null,
    avatarUrl: sessionUser?.image || null,
    profileUrl: sessionUser?.profileUrl || `https://github.com/${githubLogin}`,
  };
}
