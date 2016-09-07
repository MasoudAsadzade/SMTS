//
// Created by Matteo on 21/07/16.
//

#ifndef CLAUSE_SHARING_CLAUSESERVER_H
#define CLAUSE_SHARING_CLAUSESERVER_H

#include <map>
#include <ctime>
#include "lib/net.h"
#include "lib/sqlite3.h"
#include "Lemma.h"
#include "Settings.h"
#include "Node.h"


class LemmaServer : public Server {
private:
    Settings &settings;
    Socket *server;
    SQLite3 *db;
    std::map<std::string, Node *> lemmas;                            // name -> lemmas
    std::map<std::string, std::map<std::string, std::list<Lemma *>>> solvers;  // name -> solver -> lemmas
protected:
    void handle_accept(Socket &);

    void handle_close(Socket &);

    void handle_message(Socket &, std::map<std::string, std::string> &, std::string &);

    void handle_exception(Socket &, SocketException &);

public:
    LemmaServer(Settings &);

    ~LemmaServer();
};

#endif //CLAUSE_SHARING_CLAUSESERVER_H
