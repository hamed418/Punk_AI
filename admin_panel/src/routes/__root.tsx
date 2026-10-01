import Providers from '@/providers';
import { Outlet, createRootRoute } from '@tanstack/react-router';

export const Route = createRootRoute({
    component: RootComponent,
    notFoundComponent: () => (
        <div className="flex h-screen w-full items-center justify-center bg-background text-text-primary">
            <div className="text-center">
                <h1 className="text-3xl font-bold text-foreground">404 - Page Not Found</h1>
                <p className="mt-2 text-sm text-text-primary">The page you are looking for does not exist.</p>
            </div>
        </div>
    ),
});

function RootComponent() {
    return (
        <Providers>
            <Outlet />
        </Providers>
    );
}