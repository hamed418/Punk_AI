import Upload from './Upload';

interface MetaConnectProps {
  onConnect?: () => void;
  disabled?: boolean;
}

function MetaConnect({ onConnect, disabled = false }: MetaConnectProps) {
  return (
    <div className='w-[55%] mx-auto'>
      <Upload
        imgSrc="/Meta.png"
        title=" META ACCOUNT VALIDATION"
        text="Connect Meta Account"
        btnLabel="Connect"
        className="w-lg! p-4!"
        btnClassName="text-[12px] font-normal! py-2.5! px-4!"
        btnOnClick={onConnect}
        disabled={disabled}
      />
    </div>
  );
}

export default MetaConnect;
