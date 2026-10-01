import React from 'react';

const BackgroundEffects: React.FC = () => {
    return (
        <div className="fixed inset-0 pointer-events-none z-0 overflow-hidden">
            {/* ── Soft Background Orbs ── */}
            <div className="absolute top-[-10%] left-[-10%] w-[600px] h-[600px] rounded-full blur-[120px] bg-primary/10 animate-pulse transition-opacity duration-1000" />
            <div className="absolute top-[40%] right-[-10%] w-[500px] h-[500px] rounded-full blur-[120px] bg-primary/5 animate-pulse transition-opacity duration-1000 delay-700" />
            <div className="absolute bottom-[-10%] left-[20%] w-[400px] h-[400px] rounded-full blur-[120px] bg-primary/5 animate-pulse transition-opacity duration-1000 delay-1000" />

            {/* ── Ultra-subtle Noise Texture ── */}
            <div 
                className="absolute inset-0 opacity-[0.015] contrast-125"
                style={{
                    backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' /%3E%3C/svg%3E")`,
                    backgroundRepeat: 'repeat',
                }}
            />
        </div>
    );
};

export default BackgroundEffects;
