import { useQueryClient } from "@tanstack/react-query";
import React, {
	createContext,
	type ReactNode,
	useCallback,
	useContext,
	useMemo,
} from "react";
import { AUTH_QUERY_KEY, useLogin, useLogout, useUser } from "../hooks/api/useAuthApi";
import type { AdminUser, AdminRole } from "../api/auth";

// ── Types ────────────────────────────────────────────────────────────────

// Re-export so rest of app can import from here
export type { AdminUser as User };

interface AuthContextType {
	user: AdminUser | null;
	loading: boolean;
	isAuthenticated: boolean;
	isAdmin: boolean;
	isSuperAdmin: boolean;
	login: (email: string, password: string) => Promise<void>;
	logout: () => void;
	// Legacy stubs (kept for backwards compatibility)
	register: (email: string, password: string, full_name: string) => Promise<void>;
	updateProfile: (data: { email?: string; password?: string; full_name?: string }) => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
	const { data: user, isLoading: loading } = useUser();
	const loginMutation = useLogin();
	const logoutMutation = useLogout();

	const login = useCallback(
		async (email: string, password: string) => {
			await loginMutation.mutateAsync({ email, password });
		},
		[loginMutation],
	);

	const logout = useCallback(() => {
		logoutMutation.mutate();
	}, [logoutMutation]);

	// Legacy stubs — admin panel has no registration flow
	const register = useCallback(async (_email: string, _password: string, _full_name: string) => {
		throw new Error("Registration is not available in the admin panel.");
	}, []);

	const updateProfile = useCallback(async (_data: object) => {
		// noop — add real impl if admin profile editing is needed
	}, []);

	const isAuthenticated = !!user;
	const isAdmin = user?.role === "admin" || user?.role === "super_admin";
	const isSuperAdmin = user?.role === "super_admin";

	const value = useMemo(
		() => ({
			user: user || null,
			loading,
			isAuthenticated,
			isAdmin,
			isSuperAdmin,
			login,
			logout,
			register,
			updateProfile,
		}),
		[user, loading, isAuthenticated, isAdmin, isSuperAdmin, login, logout, register, updateProfile],
	);

	return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
	const context = useContext(AuthContext);
	if (context === undefined) {
		throw new Error("useAuth must be used within an AuthProvider");
	}
	return context;
};
