# PA-100D-Amp-Control
- This python script was created *with* AI assistance (Gemini)
- It was based on work by the node red control by Charlie Rubenstein (KB8CR) , client/server control by Mario Pagliari (IW7DLE), and from Luca (EA8DRJ).
- Setting up container for Thetis - this replaces the client/server structure. https://github.com/pharmaw/Juma100D-remote-control

It is *terminal* based python script with (gemini assistance)
.that handles the client/server with one small script.
It can run locally on computer or run on other lan connected computer in ssh terminal.

It will accept hotkeys as shown. In linux it needs a tmux shell to accept hotkeys.
It does work with thetis containers, however some of the variables are different from the IW7DLE client/server variables. Your container will need tweaking.
It does work stand alone supporting connection to other SDR software, like AetherSDR.
- when doing this it will run in a terminal window along side other SDR software.
- To change amp settings you need to have the terminal window activated on top, press hotkey, return to SDR software.
  
It can run on linux or windows (not tested on mac). 



Linux (tmux) Termninal
<img width="836" height="314" alt="image" src="https://github.com/user-attachments/assets/622e76be-e5f5-4f91-8ec8-e67c259b8433" />
Window (powershell) Terminal
<img width="839" height="396" alt="image" src="https://github.com/user-attachments/assets/49847322-0b64-4eea-85dd-193e119db328" />



 
