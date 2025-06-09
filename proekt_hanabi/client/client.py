import socket, json, threading

HOST, PORT = '0.0.0.0', 12345

class Client:
    def __init__(self):
        '''Connect to server and create file-like reader'''
        self.sock = socket.socket()
        self.sock.connect((HOST, PORT))
        self.sock_file = self.sock.makefile('r')
        self.idx = None  # assigned by server in first message
        self.game_started = False

        # Start listener thread
        threading.Thread(target=self.receive_loop, daemon=True).start()

        # Send JOIN immediately after connecting
        name = input("Your name> ")
        old_id  = input("Game ID to resume (leave blank for new)> ").strip() or None
        join_payload = {
            "type":   "JOIN",
            "player": name
        }
        if old_id:
            join_payload["game_id"] = old_id
        join_msg = json.dumps(join_payload) + "\n"
        self.sock.sendall(join_msg.encode())

    def receive_loop(self):
        while True:
            line = self.sock_file.readline()
            if not line:
                print("Connection closed by server.")
                break
            msg = json.loads(line)
            msg_type = msg.get("type")
            if msg_type == "ASSIGN_IDX":
                self.idx = msg.get("idx")
                print(f"Assigned player index: {self.idx}")
            elif msg_type == "STATE":
                # First STATE marks game start
                if not self.game_started:
                    print("All players joined. Game is starting!\n")
                    self.game_started = True
                self.handle_state(msg)
            elif msg_type == "ERROR":
                print("Error from server:", msg.get("msg"))

    def handle_state(self, state):
        ''' Prints received state and prompts for action if neccessary'''
        self.current_turn = state.get("current_turn")
        print("--- Game State ---")
        print("Board:", state.get("board"))
        print("Tokens:", state.get("tokens"), "Misfires:", state.get("misfires"))
        for i, hand in enumerate(state.get("hands", [])):
            if i == self.idx:
                # Show only the hints for your own cards
                display = []
                for card_info in hand:
                    # card_info is a dict with 'number','color','hints'
                    hints = card_info.get('hints', [])
                    display.append({'hints': hints})
                print(f"Player {i} (you): {display}")
            else:
                print(f"Player {i}: {hand}")
        print(f"Current turn: {self.current_turn}")
        # Prompt to play only on your turn
        if self.game_started and self.idx == self.current_turn:
            self.prompt_action()

    def prompt_action(self):
        while True:
            cmd = input("Your move (PLAY idx / HINT p val / DISC idx): ").strip()
            parts = cmd.split()
            if not parts:
                print("Empty command—try again")
                continue

            action = parts[0].upper()
            if action == "PLAY":
                if len(parts) != 2 or not parts[1].isdigit():
                    print("Usage: PLAY <card_idx>")
                    continue
                msg = {
                    "type": "PLAY",
                    "player_idx": self.idx,
                    "card_idx": int(parts[1])
                }
                break

            elif action == "DISC":
                if len(parts) != 2 or not parts[1].isdigit():
                    print("Usage: DISC <card_idx>")
                    continue
                msg = {
                    "type": "DISC",
                    "player_idx": self.idx,
                    "card_idx": int(parts[1])
                }
                break

            elif action == "HINT":
                # must be exactly 3 parts: HINT <player> <val>
                if len(parts) != 3:
                    print("Usage: HINT <player_idx> <color|number>")
                    continue

                target_str, val = parts[1], parts[2]
                if not target_str.isdigit():
                    print("Second argument must be the target player index.")
                    continue
                target = int(target_str)

                if val.isdigit():
                    msg = {
                        "type": "HINT",
                        "from": self.idx,
                        "to": target,
                        "number": int(val)
                    }
                else:
                    msg = {
                        "type": "HINT",
                        "from": self.idx,
                        "to": target,
                        "color": val.upper()
                    }
                break
            else:
                print("Unknown command. Use PLAY, DISC, or HINT.")
                continue

            # send well-formed message after loop broken 
        self.sock.sendall((json.dumps(msg) + "\n").encode())

if __name__ == "__main__":
    import threading
    client = Client()
    # keep the main thread alive
    threading.Event().wait()
