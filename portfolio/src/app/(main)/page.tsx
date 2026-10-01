import Spotlight from "./_components/Spotlight";
import AudioPlayer from "./_components/AudioPlayer";
import Navbar from "@/layout/navbar";
import PortfolioSection from "./_components/PortfolioSection";
// import Footer from "@/layout/footer";

export default function MainPage() {
  return (
    <>
      <Spotlight />
      <AudioPlayer />
      <div className="relative z-10 h-full grid grid-rows-[auto_1fr] px-6 sm:px-12 py-10 gap-0">
        <Navbar />
        <main className="flex flex-col items-center justify-center text-center gap-10">
          <img
            src="/monkeys.png"
            alt="Empty"
            className="h-[clamp(138px,22vh,246px)] w-auto select-none"
          />
          <PortfolioSection />
        </main>
      </div>
      {/* <Footer /> */}
    </>
  );
}



