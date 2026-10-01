import { Box } from "@mantine/core";

const Banner = () => {
    return (
        <Box className="border-[#FFFFFF12] border-b">
            <Box
                className="relative overflow-hidden py-20 md:py-28 px-4 text-center max-w-375 mx-auto "
                style={{
                    background: "radial-gradient(62.5% 135.52% at 50% -10%, rgba(255, 216, 200, 0.22) 0%, rgba(255, 223, 238, 0.08) 42%, rgba(255, 211, 231, 0) 72%)"
                }}
            >
                <Box className="relative z-10 mx-auto flex max-w-3xl flex-col items-center gap-4">
                    {/* Status Pill */}
                    <Box className="inline-flex items-center gap-2 rounded-full border border-[#FFFFFF12] bg-white/5 px-4 py-1.5 text-[11.5px]! text-primary-text/60 font-medium">
                        <span className="h-1.5 w-1.5 rounded-full bg-[#34D399] animate-pulse" />
                        <span>All systems operational &bull; Replies within 24h</span>
                    </Box>

                    {/* Main Heading */}
                    <h1 className="mt-2.5 text-4xl font-semibold tracking-[-1.08px]! leading-[58.32px]! text-[#F5EFE9]! sm:text-5xl md:text-[54px]!">
                        How can we help?
                    </h1>

                    {/* Description */}
                    <p className="max-w-lg text-sm md:text-[15.5px]! font-normal text-primary-text/52 leading-[24.8px]!">
                        Most answers live below. If yours doesn&apos;t, email us and a human will get back to you.
                    </p>
                </Box>
            </Box>
        </Box>
    );
};

export default Banner;